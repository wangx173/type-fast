# Configuration

- [OpenAI API key](#openai-api-key)
- [Azure AI Foundry](#azure-ai-foundry)
- [Model](#model)
- [Where settings are stored](#where-settings-are-stored)

## OpenAI API key

The easiest way is from the app: **Settings → Set OpenAI API Key…** (⌘,). The
key is saved to `~/.type-fast/api_key` and applied immediately, unless the
`OPENAI_API_KEY` environment variable is set (it takes precedence) or
[Azure AI Foundry](#azure-ai-foundry) is configured.

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

To route translations through a Microsoft (Azure AI) Foundry model, set the
Foundry endpoint and API key:

```sh
export AZURE_AI_ENDPOINT='https://<resource>.services.ai.azure.com'
export AZURE_AI_API_KEY='<your-foundry-key>'
# Optional: pick a specific model/deployment (defaults to gpt-4.1-mini)
export AZURE_AI_MODEL='gpt-4.1-mini'
```

When both `AZURE_AI_ENDPOINT` and `AZURE_AI_API_KEY` are set, Foundry takes
precedence over OpenAI. The endpoint may be the bare resource URL, as above, or
already include the `/openai/v1` path. Requests use Foundry's OpenAI-compatible
Responses API.

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

Choose **Settings → Set Model…** to pick a model from the list or type any
model or deployment name. Leave it blank to go back to the default
(`gpt-4.1-mini`). The choice applies to the active provider and is saved under
`~/.type-fast/`. An environment variable takes precedence over the file:

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
| `api_key`           | OpenAI API key                                                         |
| `openai_model`      | OpenAI model override                                                  |
| `azure_ai_endpoint` | Azure AI Foundry endpoint                                              |
| `azure_ai_api_key`  | Azure AI Foundry API key                                               |
| `azure_ai_model`    | Azure AI Foundry model or deployment override                          |

Built-in defaults, such as the default model, suggested models, temperature,
languages, tone presets, debounce interval, default hotkey, and transparency
presets, live in
[`type_fast/config.py`](../type_fast/config.py).
