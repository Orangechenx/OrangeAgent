# VMP 脱壳辅助指南

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

## 脱壳后步骤

- 找到入口点后 dump DEX
- 用 `@unidbg_agent` 模拟执行被抽取的方法
- 用 `@trace_agent` 追踪 VMP 解释器执行流
