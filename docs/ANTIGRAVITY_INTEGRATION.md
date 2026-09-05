# Antigravity 引擎集成与双引擎架构文档 (`ANTIGRAVITY_INTEGRATION.md`)

本文档记录了 `wechat-agy-sidecar` 与 Google Antigravity 运行时的集成架构、双引擎机制（`agy` vs `agentapi`）、CSRF Token 的生命周期约束，以及无缝容灾降级方案。

---

## 1. 背景与核心挑战

在 Antigravity 生态中，将微信客户端（通过 WeChat iLink Bot 协议）桥接至 Antigravity 时，面临以下运行模式与约束：

1. **Remote Control Web UI 同步需求**：
   - 用户希望在微信发起的对话能够在 Antigravity Remote Control Web UI（`https://antigravity.google.com`）中实时可见并支持多端协同。
   - `agentapi` CLI（基于 gRPC / ConnectRPC 连接 `localhost:4400`）负责与常驻后台的 Remote Control 守护进程通信，后者维护连接到云端 `jetski-webchannel.googleapis.com` 的 WebChannel 隧道。

2. **CSRF Token 生命周期与守护进程重启**：
   - 远程控制服务 `agy-remote-control.service` 会在每日 UTC 00:00:00 由定时器 `agy-remote-control-update.timer` 触发更新与重启。
   - 在重启过程中，Language Server（端口 4400）会在内存中重新生成全新的随机 CSRF Token（由 Go `uuid.New().String()` 生成），并且**不会落盘**。
   - 外部独立运行的守护进程（如 `wechat-agy-sidecar.service`）无法直接向 `localhost:4400` 发起未授权请求来探测新 Token（服务端由 `CsrfInterceptor` 拦截，无 Token 直接返回 401/404）。
   - 如果继续使用 `agentapi`，由于缺乏新 Token，调用会报错：
     ```json
     {"error": "failed to fetch available models: rpc error: code = Unauthenticated desc = missing CSRF token"}
     ```

3. **Remote Control 对 Native Sidecar 监督的现状**：
   - 完整的交互式 Antigravity 运行时支持本地 Sidecar 进程树管理，但在轻量后台守护进程模式（`agy --remote-control`）下，暂未内置对 `~/.gemini/config/sidecars/` 的自动拉起与监督。
   - 因此，`wechat-agy-sidecar` 必须作为独立的 systemd 用户服务运行。

---

## 2. 双引擎架构设计 (Dual-Engine Architecture)

为了同时兼顾 **极致可用性（Usability First）** 与 **Web UI 实时协同（Remote Control Sync）**，本项目实现了双引擎透明切换与智能容灾架构：

```
                    +--------------------------------+
                    |    WeChat User Message         |
                    +----------------+---------------+
                                     |
                                     v
                    +--------------------------------+
                    |    AntigravityAgent            |
                    |    Engine Router / Fallback    |
                    +-------+----------------+-------+
                            |                |
             [engine="agy"] |                | [engine="agentapi"]
                            v                v
       +----------------------------+   +----------------------------+
       | agy CLI (Native Headless)  |   | agentapi CLI (Daemon RPC)  |
       | - agy --output-format json |   | - localhost:4400 gRPC      |
       | - No CSRF token needed     |   | - Syncs with Web UI        |
       | - 100% immune to restarts  |   | - Requires valid CSRF      |
       +--------------+-------------+   +--------------+-------------+
                      |                                |
                      |                                | (On 401 / CSRF Error)
                      |                                +--- Auto-Fallback --->+
                      |                                                       |
                      v                                                       v
         [Direct Agent Output]                                    [Fallback to agy]
```

### 引擎对比

| 特性 / 考量 | `agy` 引擎 (默认首选) | `agentapi` 引擎 |
| :--- | :--- | :--- |
| **可执行文件** | `~/.local/bin/agy` | `~/.gemini/antigravity-cli/bin/agentapi` |
| **调用协议** | 独立非交互进程 CLI (`--print=...`) | 本地 gRPC / ConnectRPC (`localhost:4400`) |
| **CSRF Token 依赖** | **完全无需 Token**（零鉴权依赖） | 依赖 Language Server 内存 Token |
| **每日重启免疫** | **100% 免疫**，永不因 Token 过期中断服务 | 每日午夜服务重启后 Token 失效 |
| **Web UI 同步** | 独立 CLI 会话（暂不同步至 Web UI） | 实时同步至 `antigravity.google.com` |
| **会话历史与轨迹** | 写入 `~/.gemini/antigravity-cli/brain/` | 写入 `~/.gemini/antigravity-cli/brain/` |
| **主动推送/监控支持** | ✅ 完美支持（Watcher 监听本地脑区轨迹） | ✅ 完美支持 |
| **多轮对话与 `/resume`** | ✅ 完美支持（`--conversation=<UUID>`） | ✅ 完美支持 |

---

## 3. 配置与使用方式

引擎选择可在配置文件 `~/.gemini/wechat_sidecar_config.json` 或环境变量 `WECHAT_AGENT_ENGINE` 中配置。

### 1. 配置文件设置 (`wechat_sidecar_config.json`)

```json
{
  "engine": "agy",
  "project_id": ""
}
```

可选参数值：
- `"agy"`（**默认推荐**）：高可用模式，直接调用 `agy` CLI，免除一切 CSRF Token 维护成本。
- `"agentapi"`：UI 同步优先模式。若遇到 CSRF Token 失效或 401 错误，系统会**自动捕获并无缝降级到 `agy` 引擎**执行，确保用户消息绝不丢失。
- `"auto"`：智能探测模式。若检测到活跃 Token 则尝试 `agentapi`，否则使用 `agy`。

### 2. 环境变量覆盖

启动守护进程时亦可通过环境变量指定：

```bash
# 强制使用 agy 引擎
export WECHAT_AGENT_ENGINE="agy"

# 或在 systemd 服务配置中覆盖
systemctl --user set-environment WECHAT_AGENT_ENGINE="agy"
```

---

## 4. CSRF Token 自动同步机制 (针对于 `agentapi` 模式)

若用户依然希望在可能的情况下使用 `agentapi` 获取 Web UI 界面同步，系统支持以下同步通路：

1. **PreInvocation Hook 自动转储 (`hooks.json`)**：
   在 `~/.gemini/config/hooks.json` 中配置了 `csrf-token-sync` 钩子：
   ```json
   {
     "hooks": {
       "PreInvocation": [
         {
           "name": "csrf-token-sync",
           "type": "command",
           "command": "bash -c 'if [ -n \"$ANTIGRAVITY_CSRF_TOKEN\" ]; then echo \"$ANTIGRAVITY_CSRF_TOKEN\" > ~/.gemini/antigravity_csrf_token; fi'"
         }
       ]
     }
   }
   ```
   只要用户在 Web UI 或 CLI 中发起任何一次会话交互，系统将自动将该环境变量写入 `~/.gemini/antigravity_csrf_token`。

2. **自动读取与降级保障**：
   - `AntigravityAgent` 在准备调用 `agentapi` 时，会优先从 `~/.gemini/antigravity_csrf_token` 加载 Token。
   - 若 Token 依然过期（如前一天夜间重启后尚未在 UI 输入），`agentapi` 报错返回 `missing CSRF token` 或 `Unauthenticated`，Sidecar 将在毫秒级内自动无缝调度 `agy` 引擎重试该请求，并在日志中记录警告，保证微信端用户立刻收到回答。

---

## 5. 总结与最佳实践

- **日常推荐**：保持默认的 `"engine": "agy"` 模式，享受极简、零维护、24 小时高可用的全自动对话与工具执行能力。
- **需要 UI 审查时**：可随时配置 `"engine": "agentapi"`，并借助内置的自动降级机制获得双重容灾保障。
