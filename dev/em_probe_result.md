# 东财行情接口探测结果

- 时间: 2026-09-21 21:22:17
- pz: 20
- 代理环境: HTTP_PROXY=http://127.0.0.1:2450 HTTPS_PROXY=http://127.0.0.1:2450

## https://push2delay.eastmoney.com/api/qt/clist/get [full-headers]
```json
{
  "ok": false,
  "layer": "connection",
  "err": "ProxyError: HTTPSConnectionPool(host='push2delay.eastmoney.com', port=443): Max retries exceeded with url: /api/qt/clist/get?pn=1&pz=20&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=",
  "ms": 597
}
```

## https://push2delay.eastmoney.com/api/qt/clist/get [min-headers]
```json
{
  "ok": false,
  "layer": "connection",
  "err": "ProxyError: HTTPSConnectionPool(host='push2delay.eastmoney.com', port=443): Max retries exceeded with url: /api/qt/clist/get?pn=1&pz=20&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=",
  "ms": 274
}
```

## https://push2.eastmoney.com/api/qt/clist/get [full-headers]
```json
{
  "ok": true,
  "layer": "http",
  "status": 200,
  "bytes": 7531,
  "preview": "'{\"rc\":0,\"rt\":6,\"svr\":183637566,\"lt\":1,\"full\":1,\"dlmkts\":\"\",\"dsc\":\"0\",\"data\":{\"total\":5917,\"diff\":[{\"f1\":2,\"f2\":11.49,\"f3'",
  "ms": 245,
  "json": true,
  "total": 5917,
  "diff_len": 20
}
```

## https://push2.eastmoney.com/api/qt/clist/get [min-headers]
```json
{
  "ok": true,
  "layer": "http",
  "status": 200,
  "bytes": 7531,
  "preview": "'{\"rc\":0,\"rt\":6,\"svr\":183636167,\"lt\":1,\"full\":1,\"dlmkts\":\"\",\"dsc\":\"0\",\"data\":{\"total\":5917,\"diff\":[{\"f1\":2,\"f2\":11.49,\"f3'",
  "ms": 282,
  "json": true,
  "total": 5917,
  "diff_len": 20
}
```

## https://82.push2.eastmoney.com/api/qt/clist/get [full-headers]
```json
{
  "ok": true,
  "layer": "http",
  "status": 200,
  "bytes": 7531,
  "preview": "'{\"rc\":0,\"rt\":6,\"svr\":183638195,\"lt\":1,\"full\":1,\"dlmkts\":\"\",\"dsc\":\"0\",\"data\":{\"total\":5917,\"diff\":[{\"f1\":2,\"f2\":11.49,\"f3'",
  "ms": 244,
  "json": true,
  "total": 5917,
  "diff_len": 20
}
```

## https://82.push2.eastmoney.com/api/qt/clist/get [min-headers]
```json
{
  "ok": true,
  "layer": "http",
  "status": 200,
  "bytes": 7531,
  "preview": "'{\"rc\":0,\"rt\":6,\"svr\":183638854,\"lt\":1,\"full\":1,\"dlmkts\":\"\",\"dsc\":\"0\",\"data\":{\"total\":5917,\"diff\":[{\"f1\":2,\"f2\":11.49,\"f3'",
  "ms": 204,
  "json": true,
  "total": 5917,
  "diff_len": 20
}
```

## https://push2.eastmoney.com/api/qt/clist/get?pn=1 [full-headers]
```json
{
  "ok": true,
  "layer": "http",
  "status": 200,
  "bytes": 7531,
  "preview": "'{\"rc\":0,\"rt\":6,\"svr\":183640826,\"lt\":1,\"full\":1,\"dlmkts\":\"\",\"dsc\":\"0\",\"data\":{\"total\":5917,\"diff\":[{\"f1\":2,\"f2\":11.49,\"f3'",
  "ms": 219,
  "json": true,
  "total": 5917,
  "diff_len": 20
}
```

## https://push2.eastmoney.com/api/qt/clist/get?pn=1 [min-headers]
```json
{
  "ok": true,
  "layer": "http",
  "status": 200,
  "bytes": 7531,
  "preview": "'{\"rc\":0,\"rt\":6,\"svr\":183640811,\"lt\":1,\"full\":1,\"dlmkts\":\"\",\"dsc\":\"0\",\"data\":{\"total\":5917,\"diff\":[{\"f1\":2,\"f2\":11.49,\"f3'",
  "ms": 198,
  "json": true,
  "total": 5917,
  "diff_len": 20
}
```
