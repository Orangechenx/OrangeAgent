# AGENT.md

## 项目目标

逆向分析某 Android APP 的请求签名算法。

## 已知信息

- 签名字段在 HTTP header 的 X-Sign 中
- 签名长度 32 字节，疑似 HMAC 或 AES
- 已抓取 trace，包含签名函数的执行流

## Trace 文件

- 汇编: data/sample_trace.txt

## 当前阶段

初步分析，确认加密算法类型。
