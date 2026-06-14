# 加密算法识别与还原

## Stance

- ✅ **适合**：从 trace 或反汇编中识别 AES / DES / RSA / MD5 / SHA / HMAC / SM 系列
- ✅ **适合**：需要提取密钥、IV、S-box 等算法参数
- ✅ **适合**：在 SO 中定位加密函数并还原调用方式
- ❌ **不适合**：算法在服务器端执行（无法逆向）
- ❌ **不适合**：自定义算法（非标准加密）（走纯逆向推理）
- 本技能假设你已经有了 trace 或反汇编结果，不是从零开始逆向 SO

---

## 1. 常量识别（找算法）

在 trace 中搜索标准算法常量：

```
trace_search(query="aes", file="code", from_line=1, limit=10)
trace_search(query="0x63 0x7c 0x77", file="rw", from_line=1, limit=5)
```

### AES 特征

| 特征 | 说明 |
|------|------|
| `aese` / `aesd` / `aesmc` / `aesimc` | ARMv8 AES 指令（最确定） |
| `0x63 0x7c 0x77 0x7b` | AES S-box 前 4 字节 |
| `0x00 0x04 0x08 0x0c` | AES ShiftRows |
| `0x01 0x02 0x04 0x08` | AES Rcon |
| 16 字节常量 KEY 或 IV | 可能直接硬编码 |

**创建假设：**

```
hypothesis_create(description="AES-128-CBC, IV 硬编码在偏移 0x7a3c", tags="aes,cbc")
```

---

### SM4 特征

| 特征 | 说明 |
|------|------|
| `0x00 0x08 0x10 0x20` | SM4 FK 常量的前几字节 |
| `0x70 0xe8 0x2d 0x48` | SM4 CK 常量 |
| 128 位分组加密+32 轮迭代 | 国密 SM4 |

### RSA 特征

```
trace_search(query="modulus", file="code", from_line=1, limit=10)
trace_search(query="0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x01", file="rw", from_line=1, limit=5)
```

- RSA 公钥指数 `0x10001`（65537）
- 大数模幂运算
- 2048/4096 位密钥

---

## 2. 通过 JADX 定位算法（Java 层）

如果算法在 Java 层：

```
jadx_search_classes_by_keyword(search_term="Cipher", search_in="class")
jadx_search_classes_by_keyword(search_term="SecretKeySpec", search_in="class")
jadx_search_classes_by_keyword(search_term="Mac.getInstance", search_in="code")
```

常见模式：

```java
// AES
SecretKeySpec key = new SecretKeySpec(keyBytes, "AES");
Cipher cipher = Cipher.getInstance("AES/CBC/PKCS5Padding");
cipher.init(Cipher.ENCRYPT_MODE, key, ivSpec);

// HMAC
Mac mac = Mac.getInstance("HmacSHA256");
mac.init(new SecretKeySpec(keyBytes, "HmacSHA256"));
```

---

## 3. 通过 Unidbg 提取算法

SO 层的算法通过 unidbg 模拟执行提取：

```
hypothesis_verify(hypothesis_id="1", evidence="unidbg 调用 native 方法返回加密结果")
@unidbg_agent 模拟执行 SO 中的加密函数
```

---

## 4. 验证还原结果

```
# 用还原的算法加密已知数据
# 与 App 产生的加密结果对比
```

**确认：**

```
hypothesis_verify(hypothesis_id="1", evidence="AES-128-CBC 算法确认，IV 从偏移 0x7a3c 提取")
```

---

## 特征常量速查表

| 算法 | 特征 S-box / 常量 | ARM64 指令 |
|------|-------------------|-----------|
| AES-128 | `63 7c 77 7b` (S-box) | `aese`, `aesd` |
| AES-256 | 同上 + 密钥长度 32 字节 | `aese`, `aesmc` |
| SM4 | `70 e8 2d 48` (CK) | 普通指令实现 |
| DES | `3c cc cc cc` (PC1) | 无专用指令 |
| MD5 | `d76a a478` (K 表) | 无 |
| SHA-256 | `6a09 e667` (H 表) | `sha256h` |
| SM3 | `79cc 4519` (初值) | 无 |
