# APK 加壳识别与应对

## Stance

- ✅ **适合**：jadx 反编译后类/方法为空、只有少量 stub 类
- ✅ **适合**：APK 体积异常小、classes.dex 只有几 KB
- ✅ **适合**：运行时才加载真正的 DEX（壳保护）
- ❌ **不适合**：代码混淆而非加壳（ProGuard/R8，走混淆处理）
- ❌ **不适合**：VMP 保护（走 VMP 脱壳技能）
- 本技能聚焦壳/加固的识别，不是通用的脱壳步骤

---

## 1. 初步识别

### 1.1 看 APK 体积和 classes.dex

```
# 命令行
ls -lh app.apk
# 解压后看
apktool_decode(apk_path="app.apk")
# 检查 classes.dex 大小——如果 <50KB 基本确定有壳
```

### 1.2 看 Application 类

```
jadx_get_main_activity_class()
jadx_search_classes_by_keyword(search_term="Application", search_in="class")
```

壳通常会替换或代理 Application 类。

### 1.3 搜壳特征

```
jadx_search_classes_by_keyword(search_term="StubApp", search_in="class")
jadx_search_classes_by_keyword(search_term="ProxyApplication", search_in="class")
```

**创建假设：**

```
hypothesis_create(description="壳类型: 360 加固", tags="packer,360")
```

---

## 2. 壳特征对照表

| 壳/加固 | 特征类/文件 | DEX 大小 | 应对策略 |
|---------|------------|---------|---------|
| **360 加固** | `libjiagu.so`, `StubApp` | <10KB | frida-unpack |
| **腾讯加固** | `libDexHelper.so`, `libshell.so` | <5KB | frida-dexdump |
| **网易易盾** | `libnqshield.so` | 不定 | 定制 Hook |
| **梆梆加固** | `libsecexe.so`, `SecShell` | <20KB | 内存 dump |
| **DexGuard** | `d.b/a.a` 等混淆类 | 不定 | 多代 dump |
| **阿里加固** | `libmobisec.so` | 不定 | 定制脚本 |
| **奇安信** | `libqvm.so` | 不定 | 待研究 |

---

## 3. 验证判断

```
# 检查壳的 SO 加载
apktool_search_string(decoded_dir="app_decoded", keyword="loadLibrary")
```

**确认或修正假设：**

```
hypothesis_verify(hypothesis_id="1", evidence="发现 libjiagu.so + StubApp，确认 360 加固")
# 或
hypothesis_reject(hypothesis_id="1", reason="未发现 360 特征，找到 libsecexe.so，改为梆梆")
```

---

## 4. 选择应对路径

| 壳类型 | 推荐操作 |
|--------|---------|
| 360 / 腾讯梆梆等商业壳 | `@frida_agent` 内存 dump |
| DexGuard 自定义壳 | `@unidbg_agent` 模拟执行 |
| 未知壳 | `@trace_agent` 追踪加载流程 |
