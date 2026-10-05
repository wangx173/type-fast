# Set up Microsoft Foundry

This guide takes you from an Azure subscription to Type Fast translating
through a model you deploy in Microsoft Foundry (formerly Azure AI Foundry).
If you already have a Foundry resource and a model deployment, skip to
[Configure Type Fast](#5-configure-type-fast). To let a script create and
configure everything, see [Set up with a script](#set-up-with-a-script).

- [1. Before you start](#1-before-you-start)
  - [Set up with a script](#set-up-with-a-script)
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
- Permission to create resources in it. With the CLI, the **Contributor** role
  on the subscription is enough; you don't need **Owner**. If you only have
  Contributor on an existing resource group, skip `az group create` below and
  use that group's name instead. In the portal, you need a role such as
  **Foundry Owner** or **Foundry Account Owner** on the subscription or
  resource group. If you can't create resources, ask your Azure administrator
  to create a Foundry resource for you and share the endpoint, an API key, and
  the deployment name through a secure channel, such as a password manager.
- For the CLI steps, the
  [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli)
  **2.80.0 or later** (check with `az version`, update with `az upgrade`).
  Sign in with `az login`.

Type Fast signs in with an **API key**, so the resource must allow key
authentication. This is the default for new resources.

### Set up with a script

If you have the Azure CLI, a script can do steps 2 to 5 for you. It asks a
few questions, such as whether to use an existing resource group or create a
new one, and suggests an answer for each; press Return to accept it.

From a clone of the repository, run:

```sh
bash scripts/setup-foundry.sh
```

Or download the script, then run it:

```sh
curl -fsSL https://raw.githubusercontent.com/wangx173/type-fast/main/scripts/setup-foundry.sh -o setup-foundry.sh
bash setup-foundry.sh
```

Don't pipe it straight into `bash`; it reads your answers from the terminal.

The script:

- Uses your current subscription, or one you pick, without changing your
  default subscription.
- Uses an existing resource group or creates one (`type-fast-rg` in
  `eastus2` unless you choose otherwise).
- Uses an existing Foundry resource or creates one, and can add a
  `type-fast` project.
- Uses an existing model deployment or deploys a model (`gpt-4.1-mini`,
  Global Standard, 50K tokens per minute unless you choose otherwise).
- Saves the endpoint, API key, and deployment name to `~/.type-fast`, with the
  key file readable only by you, and makes Azure AI Foundry the provider. It
  asks before replacing existing settings.
- Sends a short test request to the deployment.

The script never deletes anything. If it stops partway, it lists what it has
already created; see [Clean up](#clean-up) to remove it. When it finishes,
continue with [6. Check that it works](#6-check-that-it-works).

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
Responses API, such as `gpt-4.1-nano` or `gpt-4.1`; see
[Cost tips](#cost-tips) before picking a larger or reasoning model.

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
subscription has a TPM quota per model and deployment type, shared by its
deployments. Global Standard quota is shared across all regions, so a
deployment in another region uses the same pool; Standard and Data Zone
Standard have their own quota. One person typing needs little; 10K–50K TPM is
plenty. If you run out of quota, lower the capacity of another deployment of
the same model and type, or request more quota in the portal. You pay for the
tokens you use, not for the capacity.

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
  `https://<resource>.services.ai.azure.com/api/projects/type-fast`, you can
  use it as is; Type Fast uses only the part before `/api/projects/`.
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

# API key: saved straight to Type Fast's key file, without showing it
mkdir -p ~/.type-fast
KEY=$(az cognitiveservices account keys list \
    --name <resource> \
    --resource-group type-fast-rg \
    --query key1 --output tsv) &&
  (umask 077; touch ~/.type-fast/azure_ai_api_key) &&
  chmod 600 ~/.type-fast/azure_ai_api_key &&
  printf '%s\n' "$KEY" > ~/.type-fast/azure_ai_api_key; unset KEY
```

Treat the API key like a password: don't paste it into chats or tickets, or
show it while sharing your screen. Either key works; having two lets you
regenerate one while the other is in use.

## 5. Configure Type Fast

Give Type Fast the endpoint and key, and the deployment name if it isn't
`gpt-4.1-mini`. The full reference is in
[Configuration → Azure AI Foundry](configuration.md#azure-ai-foundry).

**In the app (easiest).** Choose **Settings → Azure AI Foundry → Set Endpoint, Key & Deployment…**. Enter
the endpoint, paste the API key, enter the deployment name, and click
**Save**. When Type Fast asks whether to use Azure AI Foundry now, click
**Yes**. You can also choose **Settings → Provider → Azure AI Foundry**, which
opens the same window if Foundry isn't set up yet. The key is saved to
`~/.type-fast/azure_ai_api_key`, readable only by your account, and the
change applies right away.

**With files.** An app opened from Finder or the Dock does not see variables
you set in your shell, so use the files in `~/.type-fast/`:

```sh
mkdir -p ~/.type-fast
echo 'https://<resource>.services.ai.azure.com' > ~/.type-fast/azure_ai_endpoint
# Only if your deployment isn't named gpt-4.1-mini:
echo '<deployment-name>' > ~/.type-fast/azure_ai_model
```

Then save the key, unless you already did with the CLI command in
[step 4](#4-get-the-endpoint-and-api-key). Run this command. When it asks for
the key, copy the key from the portal again (copying the command replaced it
on your clipboard), then paste it and press Return. The key isn't shown or
saved in your shell history, and the file is readable only by your account:

```sh
printf 'Foundry API key: '; read -rs KEY && [ -n "$KEY" ] && \
  (umask 077; touch ~/.type-fast/azure_ai_api_key) && \
  chmod 600 ~/.type-fast/azure_ai_api_key && \
  printf '%s\n' "$KEY" > ~/.type-fast/azure_ai_api_key; echo; unset KEY
```

**Running from a terminal.** Environment variables work too, and take
precedence over the files:

```sh
export AZURE_AI_ENDPOINT='https://<resource>.services.ai.azure.com'
# Prompt for the key so it isn't saved in your shell history:
printf 'Foundry API key: '; read -rs AZURE_AI_API_KEY; echo
export AZURE_AI_API_KEY
export AZURE_AI_MODEL='<deployment-name>'  # optional
```

Don't put the key in `~/.zshrc` or other dotfiles; use the key file instead.

Notes:

- The endpoint can be the bare resource URL, as above, or already end in
  `/openai/v1`. Type Fast adds `/openai/v1` when it's missing, and ignores a
  trailing `/`.
- Type Fast uses the provider checked in **Settings → Provider**. Until you
  pick one there, it uses Foundry whenever both an endpoint and a key are
  found, even if an OpenAI key is also set. If you picked OpenAI earlier,
  choose **Settings → Provider → Azure AI Foundry**.
- To change the deployment later, choose
  **Settings → Azure AI Foundry → Set Deployment…**.
  It's saved to `~/.type-fast/azure_ai_model`. If `AZURE_AI_MODEL` is set, it
  pins the deployment and the app asks you to unset it first.
- Changes made in the app apply right away. If you change the files, or run
  the [setup script](#set-up-with-a-script), while Type Fast is open, switch to
  Type Fast and it picks them up. After changing environment variables, quit
  Type Fast (⌘Q) and start it again from that shell.

## 6. Check that it works

1. Open Type Fast. The bottom of the window shows the provider and model:
   **Azure · gpt-4.1-mini** (or your deployment name), and
   **Settings → Provider** has **Azure AI Foundry** checked. Hover over the
   provider and model to see the endpoint's host name. If it shows
   **OpenAI · …**, choose **Settings → Provider → Azure AI Foundry**.
2. Type a sentence, such as `Thank you for your help.`, and end it with a
   period. The translation should stream into the lower box within a second or
   two.

If you see `[error] …` in the lower box instead, see
[Troubleshooting](#troubleshooting).

## Troubleshooting

Errors from Foundry appear in the output box as
`[error] Error code: <status> - {…}`, followed by Foundry's message.

### The window shows OpenAI · …, or `[error] No OpenAI API key found…`

Type Fast is using OpenAI. Choose **Settings → Provider → Azure AI Foundry**.
Don't add an OpenAI key; **Settings → OpenAI → Set API Key…** sets only an
OpenAI key and doesn't configure Foundry.

### "Azure AI Foundry isn't set up", at the bottom of the window or in the output box

Azure AI Foundry is the chosen provider, but Type Fast didn't find both an
endpoint and a key. Choose **Settings → Azure AI Foundry → Set Endpoint, Key & Deployment…** and enter
them. If you used `export` but opened the app from Finder or the Dock, it
can't see those variables; set them in the app or use the
[`~/.type-fast/` files](#5-configure-type-fast) instead.

### 401 — "Access denied due to invalid subscription key or wrong API endpoint"

- The key is wrong, or belongs to a different resource than the endpoint.
  Copy both again from the same resource.
- The key was regenerated. Copy the new one.

### 403 — access denied

- "Key based authentication is disabled for this resource"
  (`AuthenticationTypeDisabled`): the resource has key authentication turned
  off, for example by an organization policy. Type Fast needs key
  authentication. Ask your administrator whether a resource that allows it can
  be provided; don't work around the policy with a personal resource for work
  content.
- "Access denied due to Virtual Network/Firewall rules" or "Public access is
  disabled": the resource only accepts requests from selected networks or
  private endpoints. Connect from an allowed network, or ask your
  administrator to allow yours.

### 404 — `DeploymentNotFound`, "The API deployment for this resource does not exist"

- The model setting doesn't match a deployment name on this resource. Type
  Fast sends the **deployment name**, which can differ from the model name
  (for example, a deployment called `translate` that runs `gpt-4.1-mini`).
  Set it in **Settings → Azure AI Foundry → Set Deployment…**,
  `AZURE_AI_MODEL`, or
  `~/.type-fast/azure_ai_model`. To list your deployments:

  ```sh
  az cognitiveservices account deployment list --name <resource> \
      --resource-group type-fast-rg --query "[].name" --output tsv
  ```

- The deployment is brand new. Wait a few minutes and try again.

### 404 — "Resource not found", without `DeploymentNotFound`

The endpoint path is wrong. Use the bare resource URL
(`https://<resource>.services.ai.azure.com`), the project endpoint (ending in
`/api/projects/<project>`), or one ending in exactly `/openai/v1`. Remove anything else, such as `/openai/deployments/…`,
`/openai/responses`, or `?api-version=…`. Type Fast uses the v1 API, which
doesn't need an `api-version`.

### 400 — other model or parameter errors

The deployment's model may not support the Responses API; deploy one of the
models in [step 3](#3-deploy-a-model). If a deployment rejects `temperature`,
Type Fast retries without it automatically.

### 429 — rate limit reached

You've used the deployment's tokens-per-minute limit. Type Fast's OpenAI
client retries a couple of times before showing the error. Wait a moment, or
raise the deployment's capacity (see [Quota](#3-deploy-a-model)).

### Connection errors

Check the resource name in the endpoint, your network, and any VPN or proxy.

## Cost tips

Type Fast translates while you type, so it makes many small requests. To keep
it fast and cheap:

- **Use a small model.** `gpt-4.1-mini` (the default) is a good balance.
  `gpt-4.1-nano` is cheaper and faster; larger models such as `gpt-4.1` cost
  more and are slower to respond.
- **Avoid reasoning models that can't turn reasoning off** (`gpt-5`,
  `gpt-5-mini`, `gpt-5-nano`, and the `o`-series) for live translation. They
  spend extra time and tokens thinking before they answer. Newer ones, such as
  `gpt-5.4-mini`, are asked not to think, so they answer quickly; it's the
  OpenAI default.
- **Use Global Standard** pay-per-token deployments. Provisioned throughput
  (PTU) is billed by the hour, whether you use it or not.
- **Set a budget.** In the Azure portal, create a budget with alerts under
  **Cost Management** for the subscription or resource group.

Check current prices on
[Azure OpenAI pricing](https://azure.microsoft.com/pricing/details/cognitive-services/openai-service/).

## Clean up

Deleting resources can't be undone. If you created a resource group just for
this guide, as in the CLI steps, check what's in it, then delete the group:

```sh
az resource list --resource-group type-fast-rg --output table
az group delete --name type-fast-rg
```

If the resource group holds anything else, such as a group you picked in the
portal, delete only the Foundry resource. Delete its projects first; the
resource can't be deleted while it has any:

```sh
az cognitiveservices account project list --name <resource> --resource-group <group> --query "[].name" --output tsv
az cognitiveservices account project delete --name <resource> --resource-group <group> --project-name type-fast
az cognitiveservices account delete --name <resource> --resource-group <group>
```

The project list shows names as `<resource>/<project>`; pass only the part
after the `/` to `--project-name`.

Deleted Foundry resources are soft-deleted, and their name stays reserved
until they're purged. To reuse the name, purge it:

```sh
az cognitiveservices account purge --name <resource> --resource-group <group> --location <region>
```

Then remove the Foundry settings and the provider choice so Type Fast goes
back to OpenAI:

```sh
rm -f ~/.type-fast/azure_ai_endpoint ~/.type-fast/azure_ai_api_key ~/.type-fast/azure_ai_model ~/.type-fast/provider
unset AZURE_AI_ENDPOINT AZURE_AI_API_KEY AZURE_AI_MODEL
```

Remove those variables from your shell profile too, if you added them, then
quit and reopen Type Fast.
