# DayTrade

Three Linux containers on Kubernetes. Newstracker is the only writer of the news and bar store. Daytrader and SouperMarket read it over HTTP.

| App | What it does | How it runs |
| --- | --- | --- |
| [Newstracker](apps/newstracker/README.md) | Polls RSS, SEC EDGAR, and Alpaca minute and daily bars into SQLite | Always-on Deployment |
| [Daytrader](apps/daytrader/README.md) | Paper scalp of the Newstracker watchlist. Entries start at 10:30 ET, each clip is 15% of the book, and a 0.5% loss is sold so a later setup can be taken. The 45% QQQ / 40% VTI sleeve stays in the code and runs only when `DAYTRADE_MODE` is not `scalp` | CronJob |
| [SouperMarket](apps/soupermarket/README.md) | Entertainment only. Daily paper, Souper Intelligence, with three commentaries. It does not place or suggest orders | Always-on Deployment |

Alpaca trading stays on the paper API. Secrets stay out of the repo and come from the `daytrade-secrets` Secret.

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
