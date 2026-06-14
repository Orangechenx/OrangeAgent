# 签名算法定位与还原

## Stance

- ✅ **适合**：App 请求头/体中有 `sign`、`_signature`、`token` 等可疑字段
- ✅ **适合**：需要从 APK 中还原签名算法用于自动化请求
- ❌ **不适合**：签名在服务端生成（不可还原）
- ❌ **不适合**：签名是服务端下发的一次性 token
- 本技能走从黑盒观察到静态逆向再到动态 Hook 的完整链路

---

## 0. 先确认目标

```
network_make_request(url="https://api.example.com/login", method="POST",
    body='{"user":"test","pwd":"123"}')
```

观察返回中是否有签名错误提示，确定签名参数名（通常叫 `sign`、`_sign`、`signature`、`token`）。

**锁定签名参数后创建假设：**

```
hypothesis_create(description="签名算法可能是 MD5(params + salt)", tags="signature,md5")
```

---

## 1. 黑盒观察（L1）

```
network_analyze_params(url="https://api.example.com/login?timestamp=xxx&sign=yyy",
    body='{"user":"test","pwd":"123"}')
```

观察：
- 参数名规律（`timestamp`、`nonce`、`sign`）
- 签名长度（32→MD5，40→SHA1，64→SHA256/HMAC）
- 是否带 `salt`、`key` 等额外参数

---

## 2. 静态定位（L2 — Java/So）

在 JADX 中搜索签名参数名：

```
jadx_search_classes_by_keyword(search_term="sign", search_in="code")
jadx_search_classes_by_keyword(search_term="signature", search_in="method")
jadx_search_classes_by_keyword(search_term="SecretKeySpec", search_in="class")
```

常见特征：
- 调用 `MessageDigest.getInstance("MD5")`、`Mac.getInstance("HmacSHA256")`
- 调用 `Base64.encodeToString`
- 拼接字符串后做 hash

**更新假设：**

```
hypothesis_verify(hypothesis_id="1", evidence="JADX 定位到 SignUtil.md5Sign() 方法")
```

---

## 3. 动态 Hook 确认（L3）

Hook 可能的签名方法：

```
frida_hook_method(class="com.example.SignUtil", method="md5Sign")
frida_hook_method(class="com.example.SignUtil", method="hmacSign")
```

如果 Java 层 Hook 不到，可能是 Native 层实现的：

```
@trace_agent JNI 调用分析
@unidbg_agent SO 模拟执行
```

---

## 4. 验证

用还原的算法自己签名发一个请求，看是否通过：

```
network_make_request(url="...", method="POST",
    headers={"X-Sign": "<你自己算的签名>"})
```

**确认后标记：**

```
hypothesis_verify(hypothesis_id="1", evidence="自签名请求通过服务端校验")
```

---

## 常见误区

- ❌ 签名参数名不一定是 `sign`，可能是 `_sig`、`token`、`verify`
- ❌ 签名字段可能在 header 里不在 body 里
- ❌ 有的 App 签名会绑定 timestamp，过期需重新抓包
