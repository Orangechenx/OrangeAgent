# VMP 脱壳辅助指南

## Stance

- ✅ **适合**：Java 方法体为空或被抽成 Native、存在 libDexHelper/libdexvm 特征
- ✅ **适合**：DEX VMP、DexGuard、360 加固、腾讯加固
- ❌ **不适合**：纯 Native 加固（走 IDA Agent）
- ❌ **不适合**：资源加密（走 Apktool Agent）
- 本技能只辅助识别壳类型和定位入口点，实际 dump 需要结合具体壳的手工操作

## 识别 VMP 壳

搜索壳的特征类/库：

```
jadx_search_classes_by_keyword(search_term="libDexHelper", search_in="class")
jadx_search_classes_by_keyword(search_term="DexGuard", search_in="class")
apktool_search_string(decoded_dir="/path/to/apk", keyword="libsecexe.so")
```

## 常见壳特征

| 特征 | 含义 |
|------|------|
| `libDexHelper` | 腾讯 VMP |
| `DexGuard` | DexGuard 商业壳 |
| `libsecexe.so` | 某加固方案的 SO 加载器 |
| `libjiagu.so` | 360 加固 |
| `libnqshield.so` | 网易易盾 |

## 脱壳后步骤

- 找到入口点后 dump DEX
- 用 `@unidbg_agent` 模拟执行被抽取的方法
- 用 `@trace_agent` 追踪 VMP 解释器执行流
- 用 `@ida_agent` 分析 SO 中的 VMP 解释器逻辑
