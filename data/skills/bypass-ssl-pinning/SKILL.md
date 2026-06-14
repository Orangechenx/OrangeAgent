# SSL Pinning 绕过指南

## 快速检查

1. 使用 `frida_bypass_ssl_pinning` 工具一键尝试
2. 如果不生效，说明 App 使用了自定义 TrustManager 或证书透明度检查

## 定位自定义 TrustManager

搜索 App 代码中的 TrustManager 实现：

```
jadx_search_classes_by_keyword(search_term="TrustManager", search_in="class")
```

找到后，搜它的校验方法：

```
jadx_search_classes_by_keyword(search_term="checkServerTrusted", search_in="method")
```

## Hook

### X509TrustManager

```
frida_hook_method(class="javax.net.ssl.X509TrustManager", method="checkServerTrusted")
```

### OkHttp CertificatePinner

```
jadx_search_classes_by_keyword(search_term="CertificatePinner", search_in="class")
```

## 注意事项

- 部分 App 会检测 Frida，需要先绕过反调试
- 证书透明度（CT）检查需要额外 Hook `java.security.cert.CertificateFactory`
