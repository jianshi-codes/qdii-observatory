# Synthetic demo

`demo.json` 与 `../universe.sample.csv` 全部为人工构造数据，不对应任何真实用户、账户、持仓或基金。加载方式：

```bash
qdii import-universe --file examples/universe.sample.csv
qdii load-demo --file examples/synthetic-demo/demo.json
```

该 demo 只验证本地数据模型、API 和 UI 空间，不验证任何实时 Provider。
