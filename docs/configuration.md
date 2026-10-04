# Configuration

- [Choose a provider](#choose-a-provider)
- [OpenAI API key](#openai-api-key)
- [Azure AI Foundry](#azure-ai-foundry)
- [Model](#model)
- [Where settings are stored](#where-settings-are-stored)

## Choose a provider

Type Fast translates with either **OpenAI** or **Azure AI Foundry**. The
bottom of the window shows which one is in use, followed by the model, for
example **OpenAI · gpt-4.1-mini** or **Azure · gpt-4.1-mini**. Hover over it
for the full provider name, and for Foundry the endpoint's host name.

To switch, choose **Settings → Provider** and pick one; the checked item is the
one in use. If the provider you pick isn't set up yet, Type Fast asks for its
key (and, for Foundry, its endpoint and deployment) first. The choice is
saved to `~/.type-fast/provider` and applies right away.

Until you pick a provider, Type Fast chooses automatically: Azure AI Foundry
when both a Foundry endpoint and key are found, and OpenAI otherwise.

## OpenAI API key

The easiest way is from the app: **Settings → OpenAI → Set API Key…** (⌘,). The
key is saved to `~/.type-fast/api_key` and applied immediately, unless the
`OPENAI_API_KEY` environment variable is set (it takes precedence). If you're
using Azure AI Foundry, Type Fast asks whether to switch to OpenAI.

Type Fast reads the key from the `OPENAI_API_KEY` environment variable or, if
that is not set, from `~/.type-fast/api_key`. The packaged app uses the file,
because an app launched from Finder does not inherit your shell environment.

```sh
# Environment variable (when running from a terminal)
export OPENAI_API_KEY='sk-...'

# Or the key file (works for the packaged app too)
mkdir -p ~/.type-fast
echo 'sk-...' > ~/.type-fast/api_key
chmod 600 ~/.type-fast/api_key  # keep the key private to your account
```

## Azure AI Foundry

New to Foundry? The [Foundry setup guide](foundry-setup.md) walks through
creating a resource, deploying a model, and finding the endpoint and key.

The easiest way is from the app: **Settings → Azure AI Foundry → Set Endpoint, Key & Deployment…**. Enter
the endpoint, API key, and deployment name, then click **Save**. The settings
are saved to the `~/.type-fast/` files below, with the key readable only by
your account, and Type Fast asks whether to switch to Foundry.

You can also set the Foundry endpoint and API key yourself:

```sh
export AZURE_AI_ENDPOINT='https://<resource>.services.ai.azure.com'
export AZURE_AI_API_KEY='<your-foundry-key>'
# Optional: pick a specific model/deployment (defaults to gpt-4.1-mini)
export AZURE_AI_MODEL='gpt-4.1-mini'
```

Unless you've picked OpenAI in [**Settings → Provider**](#choose-a-provider),
Foundry is used when both an endpoint and a key are found. The endpoint may be
the bare resource URL, as above, a project endpoint ending in
`/api/projects/<project>`, or one that already includes the `/openai/v1` path.
Requests use Foundry's OpenAI-compatible Responses API.

As with the OpenAI key, each variable has a `~/.type-fast/` fallback file so
the packaged app works when launched from Finder:

```sh
mkdir -p ~/.type-fast
echo 'https://<resource>.services.ai.azure.com' > ~/.type-fast/azure_ai_endpoint
echo '<your-foundry-key>' > ~/.type-fast/azure_ai_api_key
chmod 600 ~/.type-fast/azure_ai_api_key
# Optional model/deployment override:
echo 'gpt-4.1-mini' > ~/.type-fast/azure_ai_model
```

## Model

Each provider keeps its own model setting, in its own submenu of **Settings**:

- **OpenAI:** choose **Settings → OpenAI → Set Model…** to pick an OpenAI model from the list or
  type any other OpenAI model name. It changes the OpenAI model even while
  Azure AI Foundry is in use.
- **Azure AI Foundry:** Foundry can only use the models you deployed, so there
  is no model list. Enter your deployment name in
  **Settings → Azure AI Foundry → Set Endpoint, Key & Deployment…**.

Leave the model or deployment blank to go back to the default
(`gpt-4.1-mini`). It's saved under `~/.type-fast/`. An environment variable
takes precedence over the file:

| Provider         | Environment variable | Fallback file                 |
|------------------|----------------------|-------------------------------|
| OpenAI           | `OPENAI_MODEL`       | `~/.type-fast/openai_model`   |
| Azure AI Foundry | `AZURE_AI_MODEL`     | `~/.type-fast/azure_ai_model` |

Reasoning models (`gpt-5*`, `o1`, `o3`, `o4` families) do not accept a
`temperature` setting, so it is omitted for them automatically. If a
custom-named deployment rejects `temperature`, the request is retried without
it, and that deployment is remembered for the rest of the session.

## Where settings are stored

Everything lives in `~/.type-fast/`:

| File                | Contents                                                               |
|---------------------|------------------------------------------------------------------------|
| `settings.json`     | Language pair, tone, custom tone, hotkey, transparency, and auto-paste |
| `provider`          | Provider picked in Settings → Provider (`openai` or `azure`)           |
| `api_key`           | OpenAI API key                                                         |
| `openai_model`      | OpenAI model override                                                  |
| `azure_ai_endpoint` | Azure AI Foundry endpoint                                              |
| `azure_ai_api_key`  | Azure AI Foundry API key                                               |
| `azure_ai_model`    | Azure AI Foundry model or deployment override                          |

Built-in defaults, such as the default model, suggested models, temperature,
languages, tone presets, debounce interval, default hotkey, transparency
presets, and the auto-paste default, live in
[`type_fast/config.py`](../type_fast/config.py).
