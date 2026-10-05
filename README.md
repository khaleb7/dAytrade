# DayTrade

Three Linux containers on Kubernetes. Newstracker is the only writer of the news and bar store. Daytrader and SouperMarket read it over HTTP.

| App | What it does | How it runs |
| --- | --- | --- |
| [Newstracker](apps/newstracker/README.md) | Polls RSS, SEC EDGAR, and Alpaca bars for the scalp universe into SQLite | Always-on Deployment |
| [Daytrader](apps/daytrader/README.md) | Cash-account scalp of the Newstracker watchlist. Overnight lots sell at 09:30 and 10:00 ET. Buys start at 10:30, stay within 0.40% of the open, and skip a name already sold today. A name can take more than one 15% clip, up to 45% of the book. One clip is held until 13:00, and the last hour before a weekend or holiday does not buy. A 0.5% loss is sold so a later setup can be taken. The QQQ/VTI sleeve runs only when `DAYTRADE_MODE` is not `scalp` | CronJob |
| [SouperMarket](apps/soupermarket/README.md) | Entertainment only. Daily paper, Souper Intelligence, with three commentaries. It does not place or suggest orders | Always-on Deployment |

Daytrader submits to `https://api.alpaca.markets` with `DAYTRADE_EQUITY_OFFSET_USD=0`. Newstracker still reads `https://data.alpaca.markets`. Secrets stay out of the repo and come from the `daytrade-secrets` Secret.

Older `scripts/` and `services/` are the previous control plane. They are not what the cluster runs.

## Build

Details, including the Rancher Desktop `k8s.io` namespace, are in [docs/distroless-images.md](docs/distroless-images.md).

From this directory (the git root), with nerdctl or Docker:

```sh
nerdctl build -f apps/newstracker/Dockerfile -t newstracker:latest .
nerdctl build -f apps/daytrader/Dockerfile -t daytrader:latest .
nerdctl build -f apps/soupermarket/Dockerfile -t soupermarket:latest .
```

Rancher Desktop's k3s reads images from the `k8s.io` containerd namespace. Build there, or load the image into it, and keep `imagePullPolicy: IfNotPresent`.

## Deploy

```sh
kubectl apply -f deploy/k8s/namespace.yaml
kubectl -n daytrade create secret generic daytrade-secrets \
  --from-env-file="$HOME/.daytrade/alpaca.env" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f deploy/k8s/newstracker.yaml
kubectl apply -f deploy/k8s/daytrader.yaml
kubectl apply -f deploy/k8s/soupermarket.yaml
```

`deploy/k8s/secret.example.yaml` lists the key names only. The live env file is expected to define `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`, `CURSOR_API_KEY`, and optionally `DAYTRADE_DISCORD_WEBHOOK_URL`.

Souper Intelligence is a ClusterIP service. Read it with:

```sh
kubectl -n daytrade port-forward svc/soupermarket 8080:8080
```

Each process posts one Discord message on startup when the webhook is set. A missing webhook does not stop the process.
