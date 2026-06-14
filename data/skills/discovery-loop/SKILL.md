# 逆向发现循环

## Stance

- ✅ **适合**：面对一个未知 APK 不知道从哪下手时
- ✅ **适合**：分析卡住、多个猜想需要验证时
- ✅ **适合**：需要系统性探索而不是随机试工具时
- ❌ **不适合**：任务目标已经明确（直接调对应技能）
- ❌ **不适合**：只需要执行一个已知步骤（如"Hook 这个方法"）
- 这个元技能教你 *怎么思考*，不是具体步骤

---

## 发现循环

逆向工程的本质是**假设驱动的探索**，不是线性执行。核心循环：

```
     ┌──────────────┐
     │   Observe    │  扫 APK、看入口、搜特征
     └──────┬───────┘
            ▼
     ┌──────────────┐
     │ Hypothesize  │  猜：这是 VMP？签名是 MD5？
     └──────┬───────┘
            ▼
     ┌──────────────┐
     │    Test      │  Hook、trace、模拟执行来验证
     └──────┬───────┘
            ▼
     ┌──────────────┐
     │   Verify     │  ✅ 证据确凿 → 深入 / 提取
     │  or Reject   │  ❌ 矛盾 → 换假设（Pivot）
     └──────┬───────┘
            │
            └── 回到 Hypothesize ──→
```

---

## 循环各阶段的工具

### 1. Observe（侦察）

目的是**收集线索**，不下结论：

```
jadx_get_main_activity_class()
jadx_search_classes_by_keyword(search_term="onCreate", search_in="method")
trace_search(query="aese|aesd", file="code", from_line=1, limit=5)
apktool_manifest(decoded_dir="/path/to/apk")
```

**产出**：线索清单，比如"发现有 libDexHelper.so"、"发现 Signature 类"

### 2. Hypothesize（假设）

每一条线索就是一条假设。**一定要创建假设**，不然 later 会忘：

```
hypothesis_create(description="壳类型是腾讯 VMP", tags="packer,vmp")
hypothesis_create(description="签名算法是 HMAC-SHA256", tags="signature,hmac")
hypothesis_create(description="加密是 AES-128-CBC, key 在 SO 里", tags="aes,cbc")
```

**多条假设并行是正常的**。先全部列出来，再逐一验证。

### 3. Test（验证）

每条假设用合适的工具验证：

| 假设类型 | 验证工具 |
|---------|---------|
| 壳类型 | `@frida_agent` 内存 dump / `@apktool_agent` 搜特征 |
| 签名算法 | `@frida_agent` Hook / `@jadx_agent` 搜代码 |
| Native 加密 | `@trace_agent` 追踪 / `@unidbg_agent` 模拟 |
| 自定义协议 | `@network_agent` 发包分析 |

### 4. Verify / Reject（确认 / 拒绝）

- **验证通过** → 深入还原，提取算法/密钥

```
hypothesis_verify(hypothesis_id="1", evidence="trace 确认 AES 指令")
```

- **验证失败** → 明确标记 dead end，避免下次重蹈覆辙

```
hypothesis_reject(hypothesis_id="1", reason="trace 无 AES 指令，排除 AES 猜想")
```

### 5. Pivot（转向）

当一个假设被拒绝后：

```
hypothesis_check_dead_end(description="AES-128-CBC")

# 返回 ⚠️ 之前走不通 → 直接换方向
# 返回 ✓ 没试过 → 可以尝试
```

回到步骤 2，选下一个假设验证。

---

## 什么时候用这个循环

```
缺少线索 ──→ Observe
线索太多 ──→ 全部创建假设 → 一个个验证
验证失败 ──→ Reject → Pivot → 下一条假设
全部失败 ──→ 回到 Observe 重新侦察
```

---

## 协作提示

当你需要另一个 Agent 的帮助时，先把假设传到给它：

```
hypothesis_list(status="active")
# → @trace_agent 请验证假设 1: AES-128 加密
```

这样对方 Agent 不用从头侦察，直接基于你的假设开始验证。
