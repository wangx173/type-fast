# Set up Microsoft Foundry

This guide takes you from an Azure subscription to Type Fast translating
through a model you deploy in Microsoft Foundry (formerly Azure AI Foundry).
If you already have a Foundry resource and a model deployment, skip to
[Configure Type Fast](#5-configure-type-fast).

- [1. Before you start](#1-before-you-start)
- [2. Create a Foundry resource and project](#2-create-a-foundry-resource-and-project)
- [3. Deploy a model](#3-deploy-a-model)
- [4. Get the endpoint and API key](#4-get-the-endpoint-and-api-key)
- [5. Configure Type Fast](#5-configure-type-fast)
- [6. Check that it works](#6-check-that-it-works)
- [Troubleshooting](#troubleshooting)
- [Cost tips](#cost-tips)
- [Clean up](#clean-up)

Each step shows the [Foundry portal](https://ai.azure.com) and the Azure CLI.
Use whichever you prefer. The portal changes from time to time, so if a label
doesn't match, see Microsoft's
[Set up Microsoft Foundry resources](https://learn.microsoft.com/azure/foundry/tutorials/quickstart-create-foundry-resources)
quickstart.

## 1. Before you start

You need:

- An **Azure subscription**. You can
  [create one for free](https://azure.microsoft.com/pricing/purchase-options/azure-account).
- Permission to create resources in it. With the CLI, the **Contributor** or
  **Owner** role on the resource group is enough. In the portal, you need a
  role such as **Foundry Owner** or **Foundry Account Owner** on the
  subscription or resource group. If you can't create resources, ask your
  Azure administrator to create them for you, or to give you the endpoint, an
  API key, and the deployment name.
- For the CLI steps, the
  [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli)
  **2.80.0 or later** (check with `az version`, update with `az upgrade`).
  Sign in with `az login`.

Type Fast signs in with an **API key**, so the resource must allow key
authentication. This is the default for new resources.

## 2. Create a Foundry resource and project

A Foundry *resource* holds your model deployments and has the endpoint and
keys Type Fast uses. A *project* inside it organizes your work in the portal.

**Portal**

1. Sign in to the [Foundry portal](https://ai.azure.com).
2. Choose **Create a new project** (or, if a project is already open, select
   its name in the upper-left corner, then **Create new project**).
3. Enter a project name, such as `type-fast`.
4. Under **Advanced options**, create or pick a **resource group** and choose
   a **region** close to you.
5. Select **Create project** and wait for the project overview page.

The portal creates the Foundry resource for the project at the same time.

**Azure CLI**

Replace the example names with your own. The resource name must be globally
unique, because it becomes part of the endpoint URL.

```sh
az group create --name type-fast-rg --location eastus2

az cognitiveservices account create \
    --name <resource> \
    --resource-group type-fast-rg \
    --kind AIServices \
    --sku S0 \
    --location eastus2 \
    --custom-domain <resource> \
    --assign-identity \
    --allow-project-management true

az cognitiveservices account project create \
    --name <resource> \
    --resource-group type-fast-rg \
    --project-name type-fast \
    --location eastus2
```

If the account command fails with `CustomDomainInUse`, the name is taken;
choose another.

## 3. Deploy a model

Type Fast uses `gpt-4.1-mini` by default. It is fast and inexpensive, which
suits translating as you type. You can deploy any chat model that supports the
Responses API, such as `gpt-4.1-nano`, `gpt-4.1`, or `gpt-5-mini`.

**Portal**

1. In your project, open the model catalog (**Discover** → **Models**, or
   **Models + endpoints** → **Deploy model**).
2. Search for **gpt-4.1-mini**, then select **Deploy**.
3. Keep the **deployment name** (by default the same as the model name, such
   as `gpt-4.1-mini`) and choose the deployment type (see below).
4. Select **Deploy**.

**Azure CLI**

List the versions and deployment types available in your region, then deploy:

```sh
az cognitiveservices model list --location eastus2 \
    --query "[?model.name=='gpt-4.1-mini'].{version:model.version,skus:join(',',model.skus[].name)}" \
    --output table

az cognitiveservices account deployment create \
    --name <resource> \
    --resource-group type-fast-rg \
    --deployment-name gpt-4.1-mini \
    --model-name gpt-4.1-mini \
    --model-version 2025-04-14 \
    --model-format OpenAI \
    --sku-name GlobalStandard \
    --sku-capacity 50
```

If the command fails with `DeploymentModelNotSupported`, that model, version,
or deployment type isn't available in your region. Pick a combination from
the list above.

**Deployment type and region**

- **Global Standard** (`GlobalStandard`) is the best default: pay per token,
  the widest model availability, and the highest default quota. Requests may
  be processed in any Azure region.
- **Data Zone Standard** (`DataZoneStandard`) keeps processing within a data
  zone, such as the US or the EU, if you need that.
- **Standard** keeps processing in the resource's region, but fewer models and
  regions offer it.

**Quota.** The capacity you give a deployment is its rate limit, in thousands
of tokens per minute (TPM); `--sku-capacity 50` means 50K TPM. Each
subscription has a TPM quota per model and region, shared by its
deployments. One person typing needs little; 10K–50K TPM is plenty. If you
run out of quota, lower the capacity of another deployment, use another
region, or request more quota in the portal. You pay for the tokens you use,
not for the capacity.

> **Note the deployment name.** Type Fast sends the *deployment* name, not the
> model name. If you name the deployment something other than `gpt-4.1-mini`,
> you'll need that name in [step 5](#5-configure-type-fast).

## 4. Get the endpoint and API key

Type Fast needs the resource endpoint, which looks like
`https://<resource>.services.ai.azure.com`, and one of its API keys.

**Portal**

- In the [Foundry portal](https://ai.azure.com), the project's overview page
  shows the **API key** and the endpoints. If you only see a *project*
  endpoint, such as
  `https://<resource>.services.ai.azure.com/api/projects/type-fast`, use the
  part before `/api/projects/`.
- Or, in the [Azure portal](https://portal.azure.com), open the Foundry
  resource and go to **Resource Management** → **Keys and Endpoint**. The
  `https://<resource>.cognitiveservices.azure.com/` endpoint shown there also
  works with Type Fast.

**Azure CLI**

```sh
# Endpoint
az cognitiveservices account show \
    --name <resource> \
    --resource-group type-fast-rg \
    --query 'properties.endpoints."AI Foundry API"' --output tsv

# API key (prints a secret; don't paste it into chats or tickets)
az cognitiveservices account keys list \
    --name <resource> \
    --resource-group type-fast-rg \
    --query key1 --output tsv
```

Treat the API key like a password. Either key works; having two lets you
regenerate one while the other is in use.

## 5. Configure Type Fast

Give Type Fast the endpoint and key, and the deployment name if it isn't
`gpt-4.1-mini`. The full reference is in
[Configuration → Azure AI Foundry](configuration.md#azure-ai-foundry).

**Packaged app (recommended).** An app opened from Finder or the Dock does not
see variables you set in your shell, so use the files in `~/.type-fast/`:

```sh
mkdir -p ~/.type-fast
echo 'https://<resource>.services.ai.azure.com' > ~/.type-fast/azure_ai_endpoint
echo '<your-foundry-key>' > ~/.type-fast/azure_ai_api_key
chmod 600 ~/.type-fast/azure_ai_api_key  # keep the key private to your account
# Only if your deployment isn't named gpt-4.1-mini:
echo '<deployment-name>' > ~/.type-fast/azure_ai_model
```

**Running from a terminal.** Environment variables work too, and take
precedence over the files:

```sh
export AZURE_AI_ENDPOINT='https://<resource>.services.ai.azure.com'
export AZURE_AI_API_KEY='<your-foundry-key>'
export AZURE_AI_MODEL='<deployment-name>'  # optional
```

Notes:

- The endpoint can be the bare resource URL, as above, or already end in
  `/openai/v1`. Type Fast adds `/openai/v1` when it's missing, and ignores a
  trailing `/`.
- When both an endpoint and a key are found, Type Fast uses Foundry instead of
  OpenAI, even if an OpenAI key is also set.
- You can also set the deployment name in the app: **Settings → Set Model…**.
  It's saved to `~/.type-fast/azure_ai_model`. If `AZURE_AI_MODEL` is set, it
  pins the model and the app asks you to unset it first.
- **Quit and reopen Type Fast** (⌘Q) after changing the endpoint or key.

## 6. Check that it works

1. Open Type Fast. At the bottom of the full window, it shows
   **Model: gpt-4.1-mini** (or your deployment name). Hover over it: the
   tooltip should read **Provider: Azure AI Foundry**. If it says
   **Provider: OpenAI**, Type Fast didn't find both the endpoint and the key.
2. Type a sentence, such as `Thank you for your help.`, and end it with a
   period. The translation should stream into the lower box within a second or
   two.

If you see `[error] …` in the lower box instead, see
[Troubleshooting](#troubleshooting).

## Troubleshooting

Errors from Foundry appear in the output box as `[error] Error code: <status>
- {…}`, followed by Foundry's message.

**"No API key set — Settings › Set OpenAI API Key…"**

Type Fast found no Foundry endpoint and key (and no OpenAI key). If you used
`export` but opened the app from Finder or the Dock, it can't see those
variables; use the [`~/.type-fast/` files](#5-configure-type-fast) instead.
Check that both `azure_ai_endpoint` and `azure_ai_api_key` exist and aren't
empty. **Settings → Set OpenAI API Key…** sets only an OpenAI key; it doesn't
configure Foundry.

**401 — "Access denied due to invalid subscription key or wrong API endpoint"**

- The key is wrong, or belongs to a different resource than the endpoint.
  Copy both again from the same resource.
- The key was regenerated. Copy the new one.
- The resource has key authentication turned off (`disableLocalAuth`), for
  example by an organization policy. Type Fast needs key authentication; ask
  your administrator, or use a resource that allows it.

**404 — `DeploymentNotFound`, "The API deployment for this resource does not
exist"**

- The model setting doesn't match a deployment name on this resource. Type
  Fast sends the **deployment name**, which can differ from the model name
  (for example, a deployment called `translate` that runs `gpt-4.1-mini`).
  Set it in **Settings → Set Model…**, `AZURE_AI_MODEL`, or
  `~/.type-fast/azure_ai_model`. List your deployments with
  `az cognitiveservices account deployment list --name <resource>
  --resource-group type-fast-rg --query "[].name" --output tsv`.
- The deployment is brand new. Wait a few minutes and try again.

**404 — "Resource not found", without `DeploymentNotFound`**

The endpoint path is wrong. Use the bare resource URL
(`https://<resource>.services.ai.azure.com`) or one ending in exactly
`/openai/v1`. Remove anything else, such as `/openai/deployments/…`,
`/openai/responses`, or `?api-version=…`. Type Fast uses the v1 API, which
doesn't need an `api-version`.

**400 — model or parameter errors**

The deployment's model may not support the Responses API; deploy one of the
models in [step 3](#3-deploy-a-model). If a deployment rejects `temperature`,
Type Fast retries without it automatically.

**429 — rate limit reached**

You've used the deployment's tokens-per-minute limit. Type Fast's OpenAI
client retries a couple of times before showing the error. Wait a moment, or
raise the deployment's capacity (see [Quota](#3-deploy-a-model)).

**Connection errors**

Check the resource name in the endpoint, your network, and any VPN or proxy.
If the resource only allows access from selected networks or private
endpoints, your Mac must be on one of them.

## Cost tips

Type Fast translates while you type, so it makes many small requests. To keep
it fast and cheap:

- **Use a small model.** `gpt-4.1-mini` (the default) is a good balance.
  `gpt-4.1-nano` is cheaper and faster; larger models such as `gpt-4.1` cost
  more and are slower to respond.
- **Avoid reasoning models** (`gpt-5*`, `o`-series) for live translation. They
  spend extra time and tokens thinking before they answer.
- **Use Global Standard** pay-per-token deployments. Provisioned throughput
  (PTU) is billed by the hour, whether you use it or not.
- **Set a budget.** In the Azure portal, create a budget with alerts under
  **Cost Management** for the subscription or resource group.

Check current prices on
[Azure OpenAI pricing](https://azure.microsoft.com/pricing/details/cognitive-services/openai-service/).

## Clean up

To remove everything this guide created, delete the resource group:

```sh
az group delete --name type-fast-rg
```

Then remove the Foundry settings so Type Fast goes back to OpenAI:

```sh
rm ~/.type-fast/azure_ai_endpoint ~/.type-fast/azure_ai_api_key ~/.type-fast/azure_ai_model
```
