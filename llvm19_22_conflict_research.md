# 用 AI 把 LLVM 19 fork 推到 22 的实战路线图

**核心结论**:metax 这次 19→22 跨 3 大版本的 rebase,**AI 能覆盖到 60-75% 的工作量,80-90% 的"机械化"问题**,但要落到这个数字必须满足三个前提:用 Claude Code(Opus 4.7 lead + Sonnet 4.6 worker)或同等能力模型做主驱动、用 stgit + Mergiraf + git rerere 把冲突先做"语法消解"再喂 LLM、并把 Anthropic 公开的"effective harness for long-running agents"模式(plan-mode + 强测试 gate + checkpoint)严格落地。**风险最大的是"silent miscompile"和"AI 编造 LLVM 22 不存在的 API"**,必须用 alive2 IR 等价校验 + clangd 索引校验 + 真实 GPU kernel 回归三道闸口拦截。预算上,纯 API 计费乐观情况 $1.5K-$5K,悲观 $20K+;走 Claude Max 20x 订阅($200/人/月)5-8 个工程师 6 个月,**总成本 ~$10K AI + 工程师工时**是最现实的路径。文末给出第一周、第一个月、6 个月的具体 milestone 与风险拦截清单。

需要先纠正一个事实点:**LLVM 22(2026-02-24 发布的 22.1.0,当前 22.1.4)在 LLVM 官方层面并未被正式标注为 LTS**。LTS RFC(https://discourse.llvm.org/t/rfc-llvm-lts/84049)还在讨论中,Phoronix 的发布报道(https://www.phoronix.com/news/LLVM-Clang-22.1-Released)按常规半年 feature release 处理,Fedora 44 计划集成 22.1.0 并保留 llvm21 兼容包(https://fedoraproject.org/wiki/Changes/LLVM-22)。建议 metax 在内部决策时按"22.1.x 双周 patch release"对待,不要假设有上游长期 backport 承诺。

---

## Part 1:AI 工具能力实测对比

下面只挑对 LLVM 规模 C++ 真有实战证据的工具排序;**结论先行:Claude Code 是唯一有"AI 写完整 C 编译器"公开案例的工具,应作为主战栈;Cursor 在 LLVM monorepo 的 indexing 痛点明显;Devin 在编译器语义改动上 ACU 不可控;Aider 适合 BYOK + 国产模型场景做副驾**。

### 主力候选:Claude Code 是当前唯一有编译器规模实战证据的工具

Anthropic 工程团队 2026 年初公开了 **Claude's C Compiler 实验**(https://www.anthropic.com/engineering/building-c-compiler , 仓库 https://github.com/anthropics/claudes-c-compiler):**16 个并行 Claude agents、~2,000 sessions、$20,000 API 成本,产出 100,000 行 Rust 写的完整 C compiler**,4 个后端(x86-64 / i686 / AArch64 / RISC-V),能够编译 Linux kernel 6.9、PostgreSQL(237 个 regression tests 通过)、SQLite、FFmpeg(7,331 个 FATE tests 通过)。文中明确写"Merge conflicts are frequent, but Claude is smart enough to figure that out"。这是目前**业界唯一规模化证明 AI 能在编译器领域做长任务工程**的案例,直接可类比到 metax 的场景。

关键能力点:**Sonnet 4.6 / Opus 4.6 已 GA 1M token context window**(平台默认价格,无 long-context 溢价,见 https://platform.claude.com/docs/en/about-claude/pricing),**实际可用约 830K tokens**,可装下 LLVM 一个完整 backend 子模块 + 相关 release notes。Claude Code 不走 RAG embedding,而是用 grep/list-dir/read 等小工具让模型 agentically 阅读代码,自己写笔记到 `CLAUDE.md`,这种模式对 LLVM 这种**结构清晰、有 cross-reference**的代码库反而比 Cursor 的 vector indexing 更有效。**专用 conflict resolution skill** 已有公开实现:Raine Virta 的 `/rebase` skill(https://raine.dev/blog/resolve-conflicts-with-claude/)会先 `git log -p -n 3 <target> -- <file>` 理解目标分支意图再合并,而不是机械选边。

**Footgun 必须在 CLAUDE.md 里堵上**:GitHub issue #32476(https://github.com/anthropics/claude-code/issues/32476)报告 Claude Code 默认偏好 `git rebase + push --force-with-lease`,在共享分支上有破坏性。CLAUDE.md 必须显式写 "NEVER force-push, ALWAYS git merge for shared branches"。Subagents **不能嵌套 spawn**(issue #4182),所以多 agent 拓扑最多 2 层。

成本:Sonnet 4.6 = **$3 / $15 per MTok**,Opus 4.6 = $5/$25,Haiku 4.5 = $1/$5;Batch API 50% 折扣,prompt caching cache-read = 标价 10%。Max 20x 订阅 **$200/人/月** 在重度使用下比 API 便宜 2-2.5×,且不消耗 token quota。**1000 commits rebase 估算**:Sonnet 4.6 + 70% cache 命中 + Batch 50% off **≈ $1.5K-$3K**;Opus 4.7 全程 **~$30K**;**最经济做法是 5-8 个工程师每人买 Max 20x = $1K-$1.6K/月,6 个月共 $6K-$10K**。

CI 集成:`anthropics/claude-code-action` v1.0 已 GA(https://github.com/anthropics/claude-code-action),GitHub Marketplace 认证,支持 Anthropic 直连 / Bedrock / Vertex / Foundry。Headless 模式 `claude -p "..."` 可在 GitLab CI / Jenkins 跑。

### 副驾候选:Aider 用于离线 / 国产模型场景

Aider 优势:**完全 BYOK,可挂任意 OpenAI 兼容 endpoint**(Qwen3-Coder / DeepSeek-V3.2 自部署 vLLM/SGLang)。这对 metax 在中国、有数据合规要求时是**唯一开源、自主可控、可用国产模型的选项**。Repo-map 用 tree-sitter 抽 symbol + PageRank 排序(https://aider.chat/docs/repomap.html),C++ 自动支持。`--auto-lint` + `--auto-test` 配合 `--test-cmd "ninja check-llvm-codegen-metax"` 可以做基础的 build-test 迭代循环。

但**没有原生 git conflict resolution**(issue #800 仍 open,https://github.com/Aider-AI/aider/issues/800),**没有 subagent / 并行**,`/run` 和 `/test` 每次仍会询问(issue #3724),要做"无人值守批处理"必须自己包脚本(`Coder.create(...)` Python API + `InputOutput(yes=True)`)。**结论**:Aider 适合作为**敏感子模块上的辅助工具或 IP 强隔离场景**,不适合做主驱动。

### 不推荐做主力的工具与具体原因

**Cursor** 在 LLVM 规模下踩坑:走 RAG indexing(本地 Merkle tree → chunks → embeddings → Turbopuffer),实测 500K+ 文件 codebase 内存占用爆炸(LLVM monorepo 远超此规模);**实际可用 context ~40-80K tokens**(名义 200K,system prompt + index 结果会吃掉 ~50%);**不支持 GitLab PR 索引**(metax 内部若用 GitLab/Gerrit 受限);Background Agents 自身 Solid→React 案例(https://cursor.com/blog/scaling-agents)是 TypeScript 重构,不是 C++ 编译器规模。

**Devin / Cognition** 强项是机械重复迁移(Nubank 100,000+ data class、Oracle Java 升级),但 SWE-bench Verified end-to-end 仅 13.86%,**1/3 PR 仍需重大返工**。Lindy 评测显示同一任务 ACU 浮动可达 5×,**1000 commits rebase 悲观 $10K-$22K 完全可能**。**致命合规问题**:Devin 默认会用你的代码训练,除非显式 opt-out——对 metax 的 GPU IP 是红线。如果用,**只在 Enterprise plan + opt-out 训练 + 仅做机械批量任务**(非语义改动)。

**GitHub Copilot Coding Agent**:CI 集成最成熟(每个 session 1 premium request,Enterprise 1000 reqs/月),但**无 self-host、不支持本地模型、中国大陆访问 GitHub.com 不稳定**,2025-12 BYOK 仅支持 Anthropic / OpenAI / xAI。可作为 GitHub 镜像辅助。

**Amazon Q Developer Code Transformation**:`/transform` **不支持 C++**,仅 Java、.NET、SQL、VMware。直接排除。

**Sourcegraph Cody Enterprise + Amp**:**Lyft 2000+ repos PHP 单体→微服务的 Batch Changes 案例(https://about.sourcegraph.com/case-studies/lyft-monolith-to-microservices)是公开数据中最接近 LLVM-fork-rebase 工作模式的**;Cody Enterprise 支持 self-host 和自带 LLM endpoint。Amp 是 SaaS,需谈判私有模型 endpoint。**强烈建议 metax 做代码检索 + Batch Changes 使用,不做主 agent**。

**Tabby / Continue.dev / Roo Code / Cline**:开源 self-hosted 路线;Tabby 主打 completion + 知识库(agent preview);Continue.dev 可接 Ollama / Qwen,但缺 clangd 原生支持(https://github.com/continuedev/continue/issues/5803);Roo Code 901K+ 安装,有 orchestrator 多 mode,**完全 client-only,代码不出本机**,可指 Qwen3-Coder-480B / DeepSeek-V3.2 自部署 endpoint。**对中国合规场景这三家组合最干净,但都需自建编排层处理 LLVM 规模批量任务**。

### 工具选型一句话决策

**主战栈** = Claude Code(Max 20x 订阅,Opus 4.7 lead + Sonnet 4.6 sub,1M context beta);**代码检索** = Sourcegraph Cody Enterprise self-hosted + clangd-index;**离线/IP 隔离子模块** = Aider + 自部署 Qwen3-Coder;**CI gate** = `anthropics/claude-code-action` + 自定义 hooks;**慎用** = Devin(opt-out 训练后仅做机械批量);**排除** = Cursor(LLVM 规模 indexing 痛)、Amazon Q(不支持 C++)、Windsurf(法律不稳)。

---

## Part 2:LLVM 19→22 的 breaking changes 与对应 AI 适用度

下面是从 LLVM 20.1.0 / 21.1.0 / 22.1.0 官方 release notes 提取的、**对 GPU backend 有直接影响**的累计变化清单。**关键判断**:大约 70% 是机械化签名/重命名变化(AI 能批处理),30% 是语义变化(必须人工 review)。

### 跨子系统的"批量 churn"机械变化(AI 适合处理)

**RemoveDIs(debug intrinsics → debug records)**是 19→22 跨度最大的批量 break。LLVM 20 起 `Instruction::moveBefore`、`getFirstNonPHI` 等用 `Instruction*` 当插入位置的方法 deprecated,改用 `BasicBlock::iterator` 重载;LLVM 22 trunk 把 `UseNewDbgInfoFormat` 全局开关硬编码 true,intrinsic 模式被砍(PR #143207)。**AI 处理模式**:全仓 grep `X->moveBefore(Y)` → `X->moveBefore(Y->getIterator())`,机械替换。文档:https://llvm.org/docs/RemoveDIsDebugInfo.html

**`nocapture` → `captures(none)`**(LLVM 21):attribute 重命名,所有 `Attribute::NoCapture` / `addAttribute("nocapture")` / TableGen IntrinsicProperties 中的 `IntrNoCapture` 全部需替换。

**TableGen `!getop` → `!getdagop`,`!setop` → `!setdagop`**(LLVM 22):.td 文件文本替换。

**lit `%T` substitution 彻底移除**(LLVM 22):所有测试中 `%T/foo` 替换为 `%t.dir/foo`,前面加 `mkdir -p %t.dir`。同步 lit 移除 Python 2.7 支持,任何 Python 2 lit hooks 必须迁 3。

**ConstantExpr `mul` 移除**(LLVM 21):`ConstantExpr::getMul(...)` → `Builder.CreateMul(...)`(常量折叠自动处理)。C API `LLVMConstMul/NUWMul/NSWMul` 删除。

**`TargetIntrinsicInfo` 类移除**(LLVM 21):**直接影响 metax**——若有自定义 `MetaxIntrinsicInfo` 注册下游 intrinsic,**必须把所有 intrinsic 定义迁回中央 `llvm/include/llvm/IR/IntrinsicsMetax.td`**,backend 通过 generated header lookup。

**Pass Manager 持续向 NewPM 移植**:LLVM 20-22 把 MachineCSE、RegUsageInfoPropagation 等 codegen pass 持续移到 NewPM(典型模式 `initializeFooPass` → `initializeFooLegacyPass` + 新增 `FooPass`)。`TargetMachine::adjustPassManager()` 已删,改 `registerPassBuilderCallbacks()`。如果 metax backend 有 `MetaxPassConfig`(legacy),应同步实现 NewPM 版本(参考 AMDGPU、X86)。

**Build system**:LLVM 20 起 `compiler-rt` 用 `LLVM_ENABLE_PROJECTS` deprecated,**必须迁 `LLVM_ENABLE_RUNTIMES`**,这是机械的 build script 替换。LLVM 22 RFC 提议 host compiler 最小要求 GCC 12.2 / Clang 14.3 / VS 2022 17.14,但 22 仍兼容 VS 2019 16.8(https://discourse.llvm.org/t/rfc-raise-the-minimum-compiler-requirements-to-move-toward-c-20/88894)。**LLVM 22 关键 break**:`clangFrontend` 不再依赖 `clangDriver`,需新链 `clangOptions`——所有 fork clang 库的下游工具 CMake target_link_libraries 都需更新。

**NVPTX / AMDGPU intrinsic 清理**(metax 若 fork 自这两个 backend 模板):LLVM 20 移除 `llvm.nvvm.bitcast.*`(改 bitcast 指令)、`llvm.nvvm.rotate.*`(改 funnel-shift)、`llvm.nvvm.ptr.gen.to.*`(改 addrspacecast)、`llvm.nvvm.ldg.global.*`(改 load + !invariant.load);LLVM 20 移除 `llvm.amdgcn.flat.atomic.fadd`、`llvm.amdgcn.global.atomic.fadd`(改 `atomicrmw fadd` + addrspace);LLVM 22 移除 `llvm.amdgcn.atomic.cond.sub.u32`(改 `atomicrmw usub_cond/usub_sat`)。**强烈建议 metax 趁这次 rebase 同步淘汰自家类似遗留 intrinsics**(`llvm.metax.bitcast.*` 等),保留 bitcode auto-upgrade 路径。

### 必须人工 review 的语义性变化(AI 高风险)

**`ConstantData` 的 uses 不再可观察**(LLVM 21,直接引用 release notes):"It is no longer permitted to inspect the uses of ConstantData. Use count APIs will behave as if they have no uses (i.e. `use_empty()` is always true)"。任何 backend / 自定义 pass 通过 `ConstantInt`/`ConstantFP` 的 `users()` / `use_empty()` 做判定的代码会**默默失效**。AI 不能机械处理。

**masked.load/store/gather/scatter align 参数移除**(LLVM 22):align 从 immediate operand 变为 attribute on pointer。**直接影响 GPU vector 操作 lowering**——签名变化 AI 能识别,但模式匹配代码 + IRBuilder 调用方式必须重写。

**SwitchInst case values 不再是 operands**(LLVM 22):`getOperand(N)` 不再返回 case 值,新 C API `LLVMGetSwitchCaseValue/SetSwitchCaseValue`。任何遍历 SwitchInst operand 的 backend code 必须重写。

**`-Wincompatible-pointer-types` 默认升级为 error**(LLVM 22):metax device runtime 中所有旧 C 风格 ptr 转换会报错。可加 `-Wno-error=incompatible-pointer-types` 临时降级,但**强烈建议借此清理**。

**Pointer arithmetic UB 优化更激进**(LLVM 20):旧式 `ptr + offset < ptr` 检查恒为 false。`-fwrapv` 不再 imply 指针;新 `-fwrapv-pointer`。GPU runtime 中地址越界检查代码要审视。

**TBAA 默认对 incompatible pointer 发不同 tag**(LLVM 20):GPU runtime 中"用 `char*` 别名访问 device memory"模式可能失效。

**callbr 不再保证 indirect labels 以 `bti`/`endbr64` 开头**(LLVM 21);**Reduced BMI 默认开启**(LLVM 22,影响 C++20 modules);**`-gkey-instructions` 在 -O>0 + DWARF 默认开启**(LLVM 22,影响 debug info 输出和 device-side debugger)。

### 重要资料来源(直接给开发者)

- LLVM 20.1.0 release notes:https://releases.llvm.org/20.1.0/docs/ReleaseNotes.html
- LLVM 21.1.0:https://releases.llvm.org/21.1.0/docs/ReleaseNotes.html
- LLVM 22.1.0:https://releases.llvm.org/22.1.0/docs/ReleaseNotes.html
- Clang 22:https://releases.llvm.org/22.1.0/tools/clang/docs/ReleaseNotes.html
- RemoveDIs 专题:https://llvm.org/docs/RemoveDIsDebugInfo.html
- New Pass Manager:https://llvm.org/docs/NewPassManager.html
- AMDGPU usage:https://llvm.org/docs/AMDGPUUsage.html
- ARM 的 LLVM 22 综述:https://developer.arm.com/community/arm-community-blogs/b/tools-software-ides-blog/posts/what-is-new-in-llvm-22

**重要警告**:LLVM release notes 历史上**只覆盖一小部分实际 API 变化**,backend 内部 header(`include/llvm/CodeGen/`、`include/llvm/MC/`、`include/llvm/Target/`)的重命名、SelectionDAG SDNode 签名调整、TableGen 输出格式微调多数不会出现在 notes 里。**强烈建议分阶段 rebase(19→20→21→22),每一步用 git log + git diff 核对自家 fork 的 patch**,而不是一次跳 4 版——这样能保留中间版本的 deprecation warning 窗口。

---

## Part 3:超出"conflict + lit 失败"之外的 16 个 AI 介入点

用户已经识别 conflict resolution 和 lit failure triage 两个核心。下面是**应该额外纳入 AI workflow 的 14 个场景**,每个都给出具体的 AI 用法、是机械化还是语义化、推荐工具。

**1. Patch series 重整与上游化扫描**:用 AI 扫 metax 全部下游 patch,分类为 **(a) 已被 upstream 合入(可删)**、**(b) 可拆成更小 commit 便于 rebase**、**(c) 应推上游(减少长期维护成本)**、**(d) dead code(upstream 现有更好实现)**。具体做法:对每个下游 patch,让 agent 取 commit message 关键词 + diff 签名,在 upstream `release/22.x..main` 历史里 grep `git log --grep` / `git log -S<symbol>`;然后基于结果生成"patch 重组建议"markdown,人工 sign-off 后 stgit 重写 series。Mono LLVM 项目的经验直接可借鉴(https://www.mono-project.com/docs/advanced/runtime/docs/llvm-backend/):"avoid downstream merge commits, push to upstream as much as possible to reduce conflict surface"。

**2. TableGen / `.td` 文件迁移**:这是 AI 最容易翻车的领域。`.td` 大量用 `multiclass` / `defm` / X-Macro,AI 只看 `.td` 看不到展开后的 `.inc`。**正确做法**:把生成的 `.inc` 文件作为 RAG 上下文一并喂入,然后让 AI 改 `.td`,改完后 `tblgen-emit` 重新生成 `.inc` 验证 diff 合理。所有 `.td` 改动**强制 human review**。

**3. update_test_checks.py 系列工具的批量重生成**:LLVM 自带 `update_test_checks.py` / `update_llc_test_checks.py` / `update_mir_test_checks.py` / `update_cc_test_checks.py` / `update_analyze_test_checks.py` / `update_mca_test_checks.py`(https://github.com/llvm/llvm-project/blob/main/llvm/utils/update_test_checks.py),识别测试文件第一行的 `; NOTE: Assertions have been autogenerated by ...` 头。AI 只需要根据这个头判断"可以放心机器重生成 vs. 手工 CHECK 必须 review"。这是**纯机械化的批量任务,Batch API 50% off 直接处理**。手动 CHECK(无 NOTE 头)和包含 metax-only target 的测试**必走人工**。实例 PR:https://github.com/llvm/llvm-project/pull/116605

**4. CMake / build script 迁移**:`LLVM_ENABLE_PROJECTS=...;compiler-rt` → `LLVM_ENABLE_RUNTIMES=compiler-rt`、`clangFrontend` 链接需补 `clangOptions`、CMake minimum version 检查。这都是机械化文本替换,AI 一次跑完。

**5. Driver 选项变化批处理**:Clang 20 移除 `clang-rename`、`le32`/`le64` target、RenderScript;Clang 21 移除 ObjC ARC migrator、ARM 汇编 default-FPU 行为变化;Clang 22 `-fsanitize=alloc-token` 新增。让 AI 扫内部脚本 / Makefile / CI 配置中是否引用了被移除选项。

**6. clang-format / clang-tidy 配置同步**:LLVM 22 新增的 clang-tidy 检查(`misc-include-cleaner`、`modernize-use-scoped-lock`、`readability-use-concise-preprocessor-directives`)是 opt-in。AI 可以扫 metax 代码评估"开启某个新 check 会产生多少 violation",生成 cost-benefit 报告,而不是无脑全开。

**7. Performance / correctness regression bisect**:跑完 llvm-test-suite + SPEC 后,任何 perf/correctness regression → AI 自动 `git bisect run scripts/bisect-run.sh`(LLVM 官方有完整文档 https://llvm.org/docs/GitBisecting.html,`exit 125` 跳过 build 失败的 commit)。AI 拿到 culprit commit + diff 后再 triage 是 (a) AI 改错的 / (b) upstream 引入的真 regression / (c) flake。

**8. `git bisect` 的 reduce + 自动 issue 报告**:bisect 出 culprit 后自动跑 `creduce` / `llvm-reduce` 生成最小复现,写 GitHub issue 包含 IR + repro。

**9. Fuzzer 找 silent miscompile**:跑 csmith / yarpgen / CLsmith / CUDAsmith 在 metax-LLVM22 vs metax-LLVM19 vs upstream-22 之间做 differential testing(YARPGen v.2 在 GCC/LLVM/ISPC 找了 122 个 bug,https://users.cs.utah.edu/~regehr/pldi23.pdf;CsmithEdge 论文 https://link.springer.com/article/10.1007/s10664-022-10146-1)。AI 负责把 fuzzer 输出 → reduce → IR 等价校验 → 自动 issue。**这是防"AI 把 conflict 解得看起来对实际错"的关键防线**。

**10. Alive2 IR 等价校验**:对每个 AI 改动 IR 变换的 patch,自动跑 `alive-tv` 验证转换前后语义等价。把 alive-tv 包成 MCP server 让 agent 主动调用。

**11. Bootstrap 验证**:`-DCLANG_ENABLE_BOOTSTRAP=On` 跑 stage1 编 stage2 stage3,**比较二进制——这是捕捉 miscompile 的 gold standard**。AI 可以触发 bootstrap、对比 stage 二进制 hash、stage diff 报告。

**12. Release notes 自动撰写**:AI 扫 metax 内部 patch 在这次 rebase 中的所有改动,自动生成 release notes 草稿(每条 patch 的"Why / What / Impact / Rollback"四段式),人工编辑后发布。

**13. 内部 wiki / patch ledger 维护**:模仿 Android `clang_source_info.md`(https://android.googlesource.com/toolchain/llvm_android/),维护 `DOWNSTREAM_PATCHES.md` 列每个下游 patch 的意图、是否拟上游化、是否可丢弃。AI 在 rebase 完成后自动更新此文件,**这个文件直接成为下次 rebase 的 system context**。

**14. CI / 编译时间优化**:LLVM 推荐组合 `cmake -G Ninja -DLLVM_CCACHE_BUILD=ON -DLLVM_USE_LINKER=lld -DLLVM_PARALLEL_LINK_JOBS=N`(https://llvm.org/docs/CMake.html),配合 `ccache` 跨 build dir 共享(`CCACHE_HASHDIR=no` + `base_dir`,https://muxup.com/2025q1/ccache-for-llvm-builds-across-multiple-directories)、distcc(https://theunixzoo.co.uk/blog/2023-10-24-llvm-ccache-distcc.html)、sccache 共享 S3。**测试加速**:`lit --num-shards=N --run-shard=K`、`lit --filter=REGEXP` 增量跑、失败优先 + 慢 test 优先(基于 `.lit_test_times.txt`)。AI 不直接做这块,但可分析 build/test 时间 outlier 给出优化建议。

**15. DebugInfo / DWARF 回归**:LLVM 22 `-gkey-instructions` 默认开启,生成的 DWARF 体积/结构改变。AI 对比 LLVM 19 vs 22 的 DWARF 输出,分类差异为"intentional / regression / debugger 不兼容",触发 device-side debugger 集成回归。

**16. C++ language mode / sanitizer 配置审计**:Clang 22 仍默认 GNU++17,但 host compiler 最小要求在调整。AI 扫 metax 内部所有 `CMAKE_CXX_STANDARD` / `-std=` / sanitizer flag,生成"哪些可以 / 应该升级到 C++20"的清单,**别一次性切**(LLVM 主线提议而非强制,见 https://discourse.llvm.org/t/rfc-raise-the-minimum-compiler-requirements-to-move-toward-c-20/88894)。

---

## Part 4:端到端 agent workflow blueprint

下面是**实际可以照着搭的 7 阶段流水线**,每阶段标了人机分工、工具组合、关键 prompt 要点。

### 阶段 1:准备(Targeting + Patch ledger)

**目标**:把 metax 全部下游 patch 切成可独立 cherry-pick 的 change unit,产出 commit ledger。

**做法**:启用 `git config rerere.enabled true` 并把 `.git/rr-cache` 推到团队共享存储(用 hook 同步,因 git 不直接支持)。配置 Mergiraf(https://mergiraf.org/)作为 `*.cpp *.h` 的 merge driver(`.gitattributes` 里 `*.cpp merge=mergiraf`),**让 Mergiraf 先吃掉约 6% 纯结构化冲突 + 大量部分冲突,AI 只看真正语义冲突的尾巴**(LWN 实测 Linux kernel 历史回放数据,https://lwn.net/Articles/1042355/)。在 `.gitconfig` 启用 `merge.conflictStyle = diff3` 让 AI 拿到 base / ours / theirs 三路上下文。用 stgit / quilt 维护下游 patch series,分桶(GPU backend / custom passes / build / tests)。

**产物**:`commits.csv`(SQLite ledger)记录每个 patch 的 sha、touched files、依赖文件 5 跳闭包(用 clangd index 抽取)、估计冲突复杂度;`DOWNSTREAM_PATCHES.md`(模仿 Android `clang_source_info.md`)。

**人工 sign-off**:order + 优先级 + 是否拟上游化的清单。

### 阶段 2:自动 cherry-pick(高吞吐)

**目标**:把"显然干净"的 commits 自动 push,只把有冲突的拦下来。

**做法**:subagent `cherry-pick-agent`(Sonnet 4.6,只读 git 权限 + 写 patch)逐个 stgit `stg push`,clean → 直接进阶段 4;有冲突 → 进阶段 3。**简单 commits(≤3 文件、≤200 行、无冲突)走 Batch API 50% off**;复杂的实时跑。每 unit 失败上限设 N 次 retry,触顶 escalate。

**人工 review**:每 100 个 clean cherry-pick 抽样 5%,确认没有 silent misuse。

### 阶段 3:Conflict 解决(高质量 / 实时)

**目标**:用 AI 解掉 Mergiraf 没消化的 80% conflict,把语义冲突送到 review。

**Prompt 设计要点**:
1. **三路输入必给**:`git show :1:file`(base)、`:2:file`(ours)、`:3:file`(theirs)。**只贴带 marker 的文件会让 LLM 误把 cherry-pick 当 random 修改**(Microsoft GMerge 论文 ISSTA'22 已验证)。
2. **Intent 元数据**:对应的 upstream commit message + 下游 commit message。
3. **Downstream invariant**:"this hunk implements Metax-specific GPU lowering for `gpu.barrier`. Preserve all `metax_*` symbols and any code under `#ifdef METAX_*`. If upstream renamed an API used here, follow the rename but preserve our extra arguments"。
4. **Few-shot examples**:从 `docs/CONFLICT_GOLDEN.jsonl`(历史正确解)按 category(rename / signature change / pass reorder / removal)和文件路径相似度检索 top-3。同时从 `docs/PAST_MISTAKES.jsonl`(以前解错的)检索同类反例——haacked 的经验(https://haacked.com/archive/2026/03/25/resolve-merge-conflicts/)证明反例比正例更能防止重犯。
5. **Tool 权限**:Read / Edit / Grep / Glob + Bash 限定子集(`git log -L:<func>:<file>`、`git log --grep=<symbol> upstream/release-22.x`、`update_*_test_checks.py`、`alive-tv` MCP)。

**Subagent**:`conflict-resolver` (Opus 4.7 lead) + `reviewer` (Sonnet 4.6,只读)做 ensemble disagreement 校验——两者 diff 不一致 → escalate。pre-commit hook 强制跑 clang-format + clang-tidy + clang-include-cleaner。**TableGen / DebugInfo / CodeGen / sanitizer 改动**强制 human review。

### 阶段 4:Build 修复

**目标**:每个 cherry-picked unit 编过。

**做法**:subagent `build-fixer` (Sonnet 4.6) + bash + read/edit。`ninja -k 0 2>build.log` 收集所有 error;**hook 把 `error:` 行 grep 出来再喂模型(token 省 100×)**。失败模式标签:`undeclared identifier` / `API rename` / `opaque pointer` / `TU dependency`。retry loop 每 file ≤3 次,失败 → 标 `BLOCKED` + escalate。多 target sharding(X86 / AMDGPU / metax)分 worker 并行。**ccache + sccache S3 共享 + distcc + LLD + Ninja** 是 LLVM 官方推荐组合。

### 阶段 5:Test 修复(用户已识别的核心场景)

**目标**:用 Part B 的决策树区分 (a) conflict 解错 vs (b) upstream 合理变化。

**决策树**(直接落地):
```
test fails →
  1. RUN line 涉及 metax-only target/feature?
       yes → 极可能 (a) conflict 解错 → diff-based debug
  2. 文件首行有 "; NOTE: Assertions have been autogenerated"?
       yes → 用 fork 刚 build 的 llc/opt 跑 update_*_test_checks.py;
              对比 BEFORE/AFTER CHECK 行;
              git blame 校验差异是否来自 upstream(作者非 metax,
              且 commit ∈ release/19.x..upstream/release-22.x)?
                 yes → (b) 合理变化,接受新 CHECK
                 no  → (a),回到代码层修
       no  → 手工 CHECK(无 autogen 头),fall through 到 (a)
```

**Prompt 模板片段**(直接可用):
```
You are triaging a failing LLVM lit test after a rebase from LLVM 19 → 22.
Test: {test_path}
Auto-generated header? {YES/NO based on first line}
RUN line target features: {extracted features}

Step 1: Re-run with --dump-input=always -vv. Output: {filecheck output}

Step 2: For each failing CHECK, classify:
  - PURE_TEXT_DRIFT     : upstream changed CHECK line's expected text
  - SEMANTIC_REGRESSION : the IR/asm output is semantically wrong
  - DOWNSTREAM_BREAK    : involves metax-only feature; we likely broke it

Step 3: For PURE_TEXT_DRIFT, run {update_script} with the fork's binary
        and propose the diff. For SEMANTIC_REGRESSION/DOWNSTREAM_BREAK,
        bisect with: git log --oneline release/19.x..HEAD -- {src files}
```

**lit / FileCheck 知识必须写进 CLAUDE.md**:`--dump-input=always` / `-vv`;`CHECK-NEXT` 严格邻接的陷阱(upstream 插一行 debug 就 break,典型 (b));`CHECK-DAG` 多个连续是 unordered set,新版禁 overlap;`CHECK-SAME` 必须同行;register 命名变化用 `[[REG:%r[0-9]+]]` capture;`opt < %s` 而非 `opt %s`(避免 ModuleID 隐式匹配)。

### 阶段 6:验证(防 silent miscompile)

**目标**:防止"看起来对实际错"。

**多层防线**:
- **csmith / yarpgen 差分测试**:metax-LLVM22 vs metax-LLVM19 vs upstream-22。
- **alive2 IR 等价校验**:任何改 IR transformation 的 patch 自动跑 `alive-tv`。
- **Bootstrap stage 比较**:stage1 编 stage2,二进制 hash 对比。
- **llvm-test-suite**(https://github.com/llvm/llvm-test-suite):SingleSource + MultiSource + External(SPEC CPU 2017),`compare.py` 对比两次 results.json。
- **GPU 真实 kernel**:metax SDK 的 CUDA/HIP/OpenCL kernel test pack;`amdhsa-loader` / `nvptx-loader` 风格的 device 端 lit 测试(https://libc.llvm.org/gpu/testing.html)。
- **Sanitizer bots**:ASAN / UBSAN / MSAN。
- **Perf regression**:>5% 阻 merge,自动 bisect。

**Subagent** `validator`(只读 + judge)汇总所有验证结果,生成风险报告。

### 阶段 7:Review & Land

每个改动开 sharded PR(按 codebase owner),`ai-author` label,AI 生成的 reasoning notes 放 PR description,reviewer rotation。post-merge:reverted hunks / reviewer 改动自动回灌 `Failure DB` 形成 feedback loop(下次 rebase 检索时自动作 few-shot 反例)。

### Cross-cutting:CLAUDE.md 推荐结构

参考 humanlayer 的 "less is more, progressive disclosure"(https://www.humanlayer.dev/blog/writing-a-good-claude-md),保持 **<200 行**,塞太多反而被忽略:

```
## What this is — fork 概述、关键目录、私有部分
## Build & Test — 唯一的命令清单(slash command 引用)
## Branch model — upstream/release-22.x、main、stgit series
## Conventions — metax_ 前缀、#ifdef METAX_PRIVATE、autogen test 头
## Conflict resolution rules — 5 条硬规则(永远不删 metax/、保留 ours 额外参数等)
## Tools you can call — git log -L、update_*_test_checks.py、alive-tv MCP
## Footguns — NEVER force-push、NEVER 删 #include 不 review、TableGen 必走 human
```

### Token / 时间 / 成本估算与优化杠杆

**1000 commits rebase 粗算**(基于 Anthropic 多 agent 系统 token 是普通 chat ~15× 的实测):
- Input ~234M tokens(1000 × 15 文件 × 500 行 × 8 tok × 1.3 lead-overhead × 3 retry)
- Output ~12M tokens
- **乐观**(Sonnet 4.6 + 70% prompt cache 命中 + Batch API 50% off)≈ **$220**
- **现实**(失败重试 + Opus 重审)≈ **$1.5K-$5K**
- **悲观**(全 Opus 4.7 + 不开 cache)≈ **$30K**

**优化杠杆**(实测有效):
1. **Prompt caching** 把 LLVM 头文件 + style guide + CLAUDE.md 设 1h cache(2× write 但 0.1× read,长任务必开,https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
2. **Batch API 50% off** 异步处理 cherry-pick 干净的、test 重生成等批量任务
3. **Model routing**:Opus 4.7 仅给 lead 和复杂 IR;Sonnet 跑 worker;Haiku 跑 grep/parse-only
4. **Hooks 预处理 build log**:只把 `error:` 行喂模型(几千 → 几百 tokens)
5. **Step budget** 每个 commit ≤30 tool calls,触顶 escalate(防 infinite helpfulness loop)
6. **`/compact` + MEMORY.md** 每 stage 完成 compact,固化决策

**最经济的方案**:5-8 工程师每人 Max 20x 订阅 $200/月 × 6 个月 = **$6K-$10K AI 成本**,加上工程师工时是主头。

### Burn-down 度量(直接照 Google 的迁移报告做)

| 维度 | 指标 | 数据源 |
|---|---|---|
| Cherry-pick 进度 | total / picked / clean / conflict / dropped | git + ledger CSV |
| Build 进度 | 各 LLVM_TARGETS 通过 / 失败模块数 | ninja log + cmake target list |
| Test 进度 | check-llvm / check-clang lit 通过率;XFAIL/UNRESOLVED 趋势 | lit 输出 schema |
| 覆盖率 | metax 自有 SDK / kernel test 通过率 | gtest + 自建 |
| AI 质量 | AI-authored hunk reverted 比例;PR review 迭代数 | git blame + PR comments |
| Cost | tokens / $ per commit;retry 次数 | LiteLLM proxy / Tokscale |
| Velocity | commits/day burn-down;预计完工日 | 线性回归 |

Google 的 ICSE'25 论文(https://arxiv.org/abs/2501.06972)是直接可参考的标杆:JUnit3→4 案例 3 个月迁移 5,359 文件 / 149K 行,**80% 改动 AI-authored,人工时间减半**。但这是 Java,LLVM Pass/IR/Codegen 复杂度更高,**实际 AI-authored 预期 50-70%**。

### Escalation 流程

**严禁让 model self-rated confidence 决定 escalate**(self-confidence 长期 miscalibrated)。改用三种客观信号:**ensemble disagreement**(Opus + Sonnet 跑同任务 diff 不一致)、**LLM-judge** 第二个模型评 1-5(<4 escalate)、**测试 pass + alive2 等价** 作为 ground truth。**目标 escalation rate 10-15%**;>20% 说明系统 miscalibrated(Galileo 数据,https://galileo.ai/blog/human-in-the-loop-agent-oversight)。Fail gracefully:N 次重试失败后返回 partial_result + 详细诊断 markdown(尝试过的 hypotheses + 卡住的 grep 输出),**永远不要让 agent 编造成功**。

---

## Part 5:metax 推荐落地路径

### 团队配置(6 个月项目假设)

**核心团队**:1 个 tech lead(LLVM 编译器 expert,负责架构决策 + AI prompt engineering)+ 4 个 LLVM 工程师(分管 IR/Pass、Backend SelectionDAG、Backend GlobalISel、Driver/Build)+ 1 个 AI infra 工程师(LangGraph 编排 + MCP server + ledger / dashboard)+ 1 个 QA / fuzzing 工程师(csmith / yarpgen / GPU kernel 回归)。**总人头 7 人**。

### 工具组合(主辅清单)

**主战栈**:Claude Code Max 20x 订阅(每人 $200/月)+ Opus 4.7 lead + Sonnet 4.6 worker + 1M context beta。**理由**:唯一有规模化编译器实战证据(CCC 实验)、原生 build/test loop、GitHub Actions GA、subagent / hooks 体系成熟。

**辅助栈**:
- **代码检索**:Sourcegraph Cody Enterprise self-hosted + clangd-index(可谈判私有模型 endpoint;Lyft 2000-repo Batch Changes 案例最贴近 LLVM-fork-rebase 工作模式)
- **批量小修改 / 离线 / IP 隔离**:Aider + 自部署 Qwen3-Coder 或 DeepSeek-V3.2(vLLM/SGLang)
- **Conflict 预消解**:Mergiraf(`*.cpp *.h` merge driver)+ git rerere(团队共享 rr-cache)
- **Patch series 管理**:stgit(模仿 Android `clang_source_info.md`)
- **Build 加速**:ccache + sccache(S3 远程)+ distcc + LLD + Ninja
- **编排**:LangGraph(checkpoint + replay)+ MCP server(包装 git log / update_*_test_checks.py / alive-tv / clangd LSP)
- **验证**:alive2 + csmith + yarpgen + bootstrap + GPU kernel pack
- **Cost 监控**:LiteLLM proxy + Tokscale + Anthropic Console
- **CI gate**:`anthropics/claude-code-action` + 自定义 PreToolUse / PostToolUse / Stop hooks
- **Observability**:LangSmith + Grafana burn-down dashboard

**慎用 / 排除**:Devin(opt-out 训练后仅做机械批量,非语义)、Cursor(LLVM 规模 indexing 痛)、Amazon Q(不支持 C++ transform)、Windsurf(法律不稳)、Copilot Coding Agent(中国合规阻断)。

### Milestone

**第一周**(基础设施 + 50 commits 试点):
- 启用 git rerere、配置 Mergiraf、启用 diff3 conflict style
- stgit 切下游 patch series 分桶
- 写第一版 CLAUDE.md(<200 行)
- 搭 LangGraph + MCP server 骨架
- 选 50 个**简单**下游 patch 做 pilot,实测 token 消耗 / AI accuracy / escalation rate
- **验收**:50 commits 跑通,token 实际消耗与估算偏差 <2×,escalation rate 10-15%

**第一个月**(scale to 300 commits + ground truth 建立):
- 扩展到 LLVM 19→20 全部下游 patch(假设 ~300 commits)
- 跑通 bootstrap + llvm-test-suite + GPU kernel smoke + alive2 + csmith 全套验证
- 建立 `Failure DB`(SQLite),开始累积 `CONFLICT_GOLDEN.jsonl` + `PAST_MISTAKES.jsonl`
- 跑通 `anthropics/claude-code-action` 在 GitHub Actions 的 PR 自动 review
- 初版 burn-down dashboard 上线
- **验收**:LLVM 19→20 完成,check-llvm / check-clang lit 通过率 ≥99%,GPU kernel pack 通过率 ≥95%

**6 个月**:
- 月 2-3:LLVM 20→21
- 月 4-5:LLVM 21→22
- 月 6:验证 + perf benchmark + 文档同步 + release notes 撰写
- **最终验收**:metax-LLVM22 在所有 metax SDK kernel 上 perf regression <2%,csmith / yarpgen 24h 无 miscompile,bootstrap stage2/stage3 通过

### 用户期望的 80-90% 覆盖率,实际能否达到

**严格回答**:**80-90% 是分维度的,不能笼统说"全覆盖 80%"**。

按维度细分(基于 Google ICSE'25 + Anthropic CCC + 本研究综合):
- **机械化变更**(API rename、签名变化、attribute 重命名、TableGen `!getop`、lit `%T`、CMake flag、include path):**AI 覆盖 90-95%**,Batch API 直接处理。这是用户期望最现实的部分。
- **Conflict resolution**:**Mergiraf 消化 ~30% + AI 处理 ~50% + 人工 ~20%**,合计 AI 自动覆盖率 ~80%。
- **Lit test failure triage**:**autogen 头的 ~70% 测试 AI 自动重生成 + 手工 CHECK ~20% AI 草稿 + 10% 人工**,合计 AI 覆盖 ~80-85%。
- **语义性变更**(ConstantData uses、masked.load align、SwitchInst case 重构、TBAA 别名变化):**AI 覆盖 30-50%**,必须人工 review。
- **Backend codegen / lowering / TableGen 改动**:**AI 覆盖 40-60%**,强制 human review。
- **Silent miscompile 检出**:**AI 不能"覆盖",但能跑 fuzzer + alive2 + bisect 自动化捕捉率 90%+**。

综合下来,用户希望的"80-90% 升级问题被 AI 解决"在**总工时**维度上是可达的,但前提是:
1. 严格分阶段(19→20→21→22)而非一次跳 4 版
2. Mergiraf + git rerere 把语法消解前置
3. 主战栈用 Claude Code Opus + Sonnet,不能用低端模型
4. 严格的人工 review gate(TableGen / DebugInfo / CodeGen / sanitizer 必走人工)
5. csmith / yarpgen / alive2 / bootstrap 四道验证防线全开
6. Failure DB feedback loop 持续迭代 prompt library

如果**任何一条 prerequisite 跳过**,实际 AI 覆盖率可能掉到 50-60%(主要因为 silent miscompile 不被检出会拖累后期 perf debug)。

### 风险与拦截清单

**风险 1:silent miscompile**——AI 把 conflict 解得"看起来对实际错"。**拦截**:csmith / yarpgen 24h 差分;alive2 IR 等价校验对所有 IR 改动强制;bootstrap stage 比较;真实 GPU kernel 回归。

**风险 2:AI 编造不存在的 LLVM 22 API**(已知失败模式)。**拦截**:clangd index + Sourcegraph 检索强制 grounding,引用必须出现在 retrieval 结果中;build error 自动回写 Failure DB 累积反例;ensemble disagreement 校验。

**风险 3:token 成本失控**。**拦截**:走 Max 20x 订阅而非 API 计费;step budget 每 commit ≤30 tool calls;Batch API 50% off 处理批量;Prompt caching 必开;Haiku 跑 grep/parse-only;监控 dashboard 周更,>$3K/周触发预警。

**风险 4:context drift**(长 session 中 agent 忘记原 plan)。**拦截**:LeadResearcher 在 200K tokens 前把 plan 写到 Memory file;`/compact` 每 stage 完成强制;subagent 隔离 context;参考 Anthropic 的 "Effective harnesses for long-running agents"(https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)。

**风险 5:`#include` 删错 / 静默 SFINAE 改变 / TableGen X-Macro 看不到展开**。**拦截**:clang-include-cleaner + IWYU CI gate;diff 中 `#include` 删除标记为高风险强制 reviewer;`.td` 改动必走 human review;把生成的 `.inc` 文件作为 RAG 上下文一并喂入。

**风险 6:Anthropic April 23 postmortem 类事件**(三个无害的 harness 改动叠加导致 Claude Code 一个月质量下降,**通过了 unit/E2E/dogfooding 多重门禁**,https://www.anthropic.com/engineering/april-23-postmortem)。**拦截**:每个 prompt / subagent 调整都做 ablation 比较,别一次叠太多 harness 改动;留 baseline pilot(不变更的 50 commits)做 regression detection。

**风险 7:LLVM 22 不是真 LTS**(本报告开头已纠正)——上游 22.1.x 双周 patch 不能假设有长期 backport。**拦截**:metax 内部建立"自维护 22-LTS"分支策略,定期 cherry-pick upstream 22.1.x 的 critical fix。

**风险 8:多 agent token 是单 chat 的 ~15×**(Anthropic 数据)。**拦截**:不滥用并行 subagent,只在 breadth-first 任务(triage 多 lit failure)用;紧耦合任务(单 commit 解 conflict)用单 agent。

**风险 9:`subagent` 不能嵌套 spawn**(issue #4182)。**拦截**:架构限定 2 层(lead + worker),不要画 3 层组织图。

**风险 10:中国合规 / 网络访问**。**拦截**:对 IP 强隔离的 metax 私有 backend(`lib/Target/Metax/`)用 Aider + 自部署 Qwen3-Coder;公共 LLVM 部分(99% rebase 工作量)用 Claude Code(走 Anthropic 直连或 Bedrock 中转);**永远不要把 metax 私有 GPU IP 提交到 Devin**(默认会训练)。

---

## 收尾:这个项目最关键的三个判断

第一,**主战栈选 Claude Code 不是因为它"最酷",而是因为它是唯一在编译器规模(100K 行 Rust C compiler)上有公开 dogfooding 证据的工具**——CCC 实验直接证明并行 agents + git lock + 强测试 harness 这套方法论能 work,metax 直接复用即可。

第二,**80-90% 覆盖率是工时维度可达,但分场景看差异巨大**——机械化变更 90%+,语义改动 30-50%,silent miscompile 必须靠 fuzzer + alive2 + bootstrap 四道防线而非靠 AI 单点。**用户对这个数字的期望应该按"AI 减少了多少工程师工时",而不是"AI 自动 merge 的 PR 比例"来衡量**。

第三,**最大的风险不是 token 成本而是 silent miscompile**——CCC 实验里 Claude 写整个 C compiler 都能跑过 7,331 个 FATE tests,反衬出"测试是 ground truth"的极端重要性。metax 应该把 csmith / yarpgen / alive2 / bootstrap / GPU kernel 回归这套验证基础设施作为**先于 AI workflow 上线的 prerequisite**——没有这套 ground truth,任何 AI 加速都会在 6 个月后以"找 miscompile bug 找不到"的形式还回去。