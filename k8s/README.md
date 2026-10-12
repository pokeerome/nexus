# Run Nexus locally on Kubernetes with minikube

This learning setup runs the app locally. It is separate from the live demo.

## Prerequisites

- Docker Desktop running, with at least 6 GB of memory allocated
- minikube, kubectl, and `uv` installed
- An OpenAI API key

## Start minikube

From the repository root in PowerShell:

```powershell
minikube start --driver=docker --cpus=4 --memory=6144
kubectl get nodes
```

## Build the images inside minikube

Build each image from the repository root. This works with minikube's default
containerd runtime and does not require `docker-env`.

```powershell
minikube image build -t nexus-backend:local backend
minikube image build -t nexus-frontend:local frontend
```

## Create the namespace and secret

Create the namespace first:

```powershell
kubectl apply -f k8s/namespace.yaml
```

Generate local database and signing secrets, then create the Kubernetes Secret.
Replace the OpenAI placeholder with your own key; do not commit the key or save
it in a manifest.

```powershell
$pw = uv run --project backend python -c "import secrets,string; print(''.join(secrets.choice(string.ascii_letters+string.digits) for _ in range(24)))"
$key = uv run --project backend python -c "import secrets; print(secrets.token_hex(32))"

kubectl create secret generic nexus-secrets -n nexus `
  --from-literal=POSTGRES_PASSWORD=$pw `
  --from-literal=SECRET_KEY=$key `
  --from-literal=OPENAI_API_KEY=PASTE_YOUR_OPENAI_KEY_HERE
```

A Kubernetes Secret is base64-encoded, not encrypted by default. Anyone with
permission to read Secrets in this local cluster can read these values.

## Deploy and wait for startup

```powershell
kubectl apply -k k8s
kubectl get pods -n nexus -w
```

Wait for `postgres`, `redis`, `backend`, and `frontend` to be `Running`, and for
`db-setup` to be `Completed`, then press Ctrl+C. The database setup Job may
retry while Postgres initializes.

```powershell
kubectl logs job/db-setup -n nexus
```

The log should include `Tables created`.

## Open the app

In a PowerShell window, run:

```powershell
kubectl port-forward -n nexus svc/frontend 8080:80
```

Keep the port-forward running and open <http://localhost:8080>.

## Inspect and update

```powershell
kubectl logs -n nexus deploy/backend -f
kubectl get all -n nexus
kubectl exec -n nexus statefulset/postgres -- psql -U nexus -d nexus -c "\dt"
```

After changing backend code, rebuild its image, then restart the deployment:

```powershell
minikube image build -t nexus-backend:local backend
kubectl rollout restart deployment/backend -n nexus
```

After changing frontend code, rebuild and restart the frontend deployment:

```powershell
minikube image build -t nexus-frontend:local frontend
kubectl rollout restart deployment/frontend -n nexus
```

The Postgres StatefulSet keeps its data on a persistent volume. Uploaded files
are stored in the backend pod's temporary volume and are lost if that pod is
recreated; the Celery worker runs in the same backend container so it can read
those files.

To rerun database setup, delete the completed Job and re-apply the manifests:

```powershell
kubectl delete job db-setup -n nexus
kubectl apply -k k8s
```

## Troubleshooting

- `ErrImageNeverPull`: build the missing image with
  `minikube image build -t <image-name>:local <backend-or-frontend>`.
- Backend `CrashLoopBackOff`: inspect
  `kubectl logs -n nexus deploy/backend --previous`.
- `CreateContainerConfigError`: verify the `nexus-secrets` Secret and its three
  required keys.
- Database setup repeatedly fails: inspect `kubectl logs job/db-setup -n nexus`.
  If the database was initialized with another password, its existing data
  volume retains that password; use the cleanup steps below to start fresh.
- `OOMKilled`: inspect pod events and raise the applicable memory limit if
  needed.
- The page opens but API calls fail: check pod readiness and keep the
  `kubectl port-forward` command running.
- `minikube start` reports insufficient memory: raise Docker Desktop's memory
  allocation or reduce the minikube `--memory` value.

## Cleanup

```powershell
kubectl delete namespace nexus
minikube stop
```

Deleting the namespace also deletes the Postgres persistent volume claim and
database data. `minikube delete` removes the entire cluster.
