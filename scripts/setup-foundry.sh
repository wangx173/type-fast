#!/usr/bin/env bash
#
# Set up Microsoft Foundry for Type Fast.
#
# Walks you through choosing (or creating) a resource group, a Foundry
# resource, and a model deployment, then saves the endpoint, API key, and
# deployment name to ~/.type-fast/, makes Azure AI Foundry Type Fast's
# provider, and sends a test request.
#
# Usage: bash scripts/setup-foundry.sh
#
# Requires the Azure CLI 2.80.0 or later, signed in with `az login`.
# See docs/foundry-setup.md for what each step does.

set -euo pipefail

DEFAULT_GROUP="type-fast-rg"
DEFAULT_LOCATION="eastus2"
DEFAULT_PROJECT="type-fast"
DEFAULT_MODEL="gpt-4.1-mini"
DEFAULT_SKU="GlobalStandard"
DEFAULT_CAPACITY="50"
MIN_AZ_VERSION="2.80.0"
CONFIG_DIR="$HOME/.type-fast"

# Some Azure CLI builds print harmless Python SyntaxWarnings on every call.
export PYTHONWARNINGS="ignore::SyntaxWarning"

SUBSCRIPTION_ID=""
GROUP=""
GROUP_LOCATION=""
RESOURCE=""
RESOURCE_LOCATION=""
DEPLOYMENT=""
ENDPOINT=""
KEY=""
CREATED=()

say() { printf '%s\n' "$*"; }
heading() { printf '\n== %s ==\n' "$*"; }
warn() { printf 'Warning: %s\n' "$*" >&2; }

die() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

on_exit() {
    local status=$?
    KEY=""
    if [ "$status" -ne 0 ] && [ "${#CREATED[@]}" -gt 0 ]; then
        printf '\nSetup stopped. These were already created and may cost money:\n' >&2
        local item
        for item in "${CREATED[@]}"; do
            printf '  - %s\n' "$item" >&2
        done
        printf 'See "Clean up" in docs/foundry-setup.md to remove them.\n' >&2
    fi
}
trap on_exit EXIT

usage() {
    sed -n '3,13p' "$0" | sed 's/^# \{0,1\}//'
}

# ask VAR "Prompt" [default]
ask() {
    local __var=$1 __prompt=$2 __def=${3-} __answer
    if [ -n "$__def" ]; then
        printf '%s [%s]: ' "$__prompt" "$__def"
    else
        printf '%s: ' "$__prompt"
    fi
    IFS= read -r __answer || die "No input; setup cancelled."
    __answer=$(printf '%s' "$__answer" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
    [ -z "$__answer" ] && __answer=$__def
    printf -v "$__var" '%s' "$__answer"
}

# confirm "Question" y|n  -> returns 0 for yes
confirm() {
    local __prompt=$1 __def=$2 __hint __answer
    if [ "$__def" = "y" ]; then __hint="Y/n"; else __hint="y/N"; fi
    while true; do
        printf '%s [%s]: ' "$__prompt" "$__hint"
        IFS= read -r __answer || die "No input; setup cancelled."
        [ -z "$__answer" ] && __answer=$__def
        case "$__answer" in
            [Yy] | [Yy][Ee][Ss]) return 0 ;;
            [Nn] | [Nn][Oo]) return 1 ;;
        esac
        say "Please answer y or n."
    done
}

# choose VAR "Prompt" item...  -> sets VAR to the chosen item
choose() {
    local __var=$1 __prompt=$2 __answer __i __item
    shift 2
    __i=1
    for __item in "$@"; do
        printf '  %d) %s\n' "$__i" "$__item"
        __i=$((__i + 1))
    done
    while true; do
        printf '%s [1-%d]: ' "$__prompt" "$#"
        IFS= read -r __answer || die "No input; setup cancelled."
        case "$__answer" in
            '' | *[!0-9]*) ;;
            *)
                if [ "$__answer" -ge 1 ] && [ "$__answer" -le "$#" ]; then
                    printf -v "$__var" '%s' "${!__answer}"
                    return 0
                fi
                ;;
        esac
        say "Enter a number from 1 to $#."
    done
}

# lines_to_array NAME < input  (bash 3.2 has no mapfile)
# Feed it from a variable that was checked, not from < <(az ...): a failed
# az call there would look like an empty list.
lines_to_array() {
    local __name=$1 __line
    eval "$__name=()"
    while IFS= read -r __line; do
        if [ -n "$__line" ]; then
            eval "$__name+=(\"\$__line\")"
        fi
    done
    return 0
}

# version_at_least HAVE NEED
version_at_least() {
    [ "$(printf '%s\n%s\n' "$2" "$1" | sort -t. -k1,1n -k2,2n -k3,3n | head -n 1)" = "$2" ]
}

# 2-64 letters, digits, and hyphens; starts and ends with a letter or digit.
valid_name() {
    printf '%s' "$1" | grep -Eq '^[A-Za-z0-9]([A-Za-z0-9-]{0,62}[A-Za-z0-9])?$'
}

# Like valid_name, but periods and underscores are allowed too (gpt-4.1-mini).
valid_deployment_name() {
    printf '%s' "$1" | grep -Eq '^[A-Za-z0-9]([A-Za-z0-9._-]{0,62}[A-Za-z0-9])?$'
}

az_sub() {
    az "$@" --subscription "$SUBSCRIPTION_ID" --only-show-errors
}

check_prerequisites() {
    heading "Checking prerequisites"
    command -v az >/dev/null 2>&1 \
        || die "The Azure CLI (az) isn't installed. See https://learn.microsoft.com/cli/azure/install-azure-cli"
    command -v curl >/dev/null 2>&1 || die "curl isn't installed."

    local version
    version=$(az version --query '"azure-cli"' --output tsv 2>/dev/null) \
        || die "Couldn't run 'az version'."
    version_at_least "$version" "$MIN_AZ_VERSION" \
        || die "Azure CLI $version is too old; $MIN_AZ_VERSION or later is required. Run 'az upgrade'."
    say "Azure CLI $version"

    if ! az account show --only-show-errors >/dev/null 2>&1; then
        say "You're not signed in to Azure."
        if confirm "Run 'az login' now?" y; then
            az login --only-show-errors >/dev/null || die "Sign-in failed."
        else
            die "Sign in with 'az login', then run this script again."
        fi
    fi
}

choose_subscription() {
    heading "Subscription"
    local current_name
    SUBSCRIPTION_ID=$(az account show --query id --output tsv --only-show-errors)
    current_name=$(az account show --query name --output tsv --only-show-errors)
    say "Current subscription: $current_name ($SUBSCRIPTION_ID)"
    if confirm "Use this subscription?" y; then
        return 0
    fi

    local subs=() choice out
    out=$(az account list --query "[?state=='Enabled'].[name, id]" \
        --output tsv --only-show-errors) || die "Couldn't list your subscriptions."
    lines_to_array subs <<<"$(printf '%s\n' "$out" | awk -F'\t' 'NF {print $1 " (" $2 ")"}')"
    [ "${#subs[@]}" -gt 0 ] || die "No enabled subscriptions found."
    choose choice "Subscription" "${subs[@]}"
    SUBSCRIPTION_ID=$(printf '%s' "$choice" | sed 's/.*(\(.*\))$/\1/')
}

choose_resource_group() {
    heading "Resource group"
    local mode
    choose mode "Resource group" "Use an existing resource group" "Create a new resource group"

    if [ "$mode" = "Use an existing resource group" ]; then
        local groups=() out
        out=$(az_sub group list --query "sort_by([], &name)[].name" --output tsv) \
            || die "Couldn't list the resource groups."
        lines_to_array groups <<<"$out"
        [ "${#groups[@]}" -gt 0 ] || die "This subscription has no resource groups. Run again and create one."
        choose GROUP "Resource group" "${groups[@]}"
        GROUP_LOCATION=$(az_sub group show --name "$GROUP" --query location --output tsv)
        return 0
    fi

    while true; do
        ask GROUP "New resource group name" "$DEFAULT_GROUP"
        if ! printf '%s' "$GROUP" | grep -Eq '^[-A-Za-z0-9_.()]{1,90}$' || [ "${GROUP%.}" != "$GROUP" ]; then
            say "Use up to 90 letters, digits, and - _ . ( ), not ending in a period."
            continue
        fi
        if [ "$(az_sub group exists --name "$GROUP")" = "true" ]; then
            say "A resource group named '$GROUP' already exists."
            if confirm "Use it?" y; then
                GROUP_LOCATION=$(az_sub group show --name "$GROUP" --query location --output tsv)
                return 0
            fi
            continue
        fi
        break
    done
    ask GROUP_LOCATION "Region for the resource group" "$DEFAULT_LOCATION"
    say "Creating resource group '$GROUP'..."
    az_sub group create --name "$GROUP" --location "$GROUP_LOCATION" --output none
    CREATED+=("resource group $GROUP")
}

choose_resource() {
    heading "Foundry resource"
    local existing=() mode="Create a new Foundry resource" out
    out=$(az_sub cognitiveservices account list --resource-group "$GROUP" \
        --query "[?kind=='AIServices' || kind=='OpenAI'].name" --output tsv) \
        || die "Couldn't list the Foundry resources in $GROUP."
    lines_to_array existing <<<"$out"

    if [ "${#existing[@]}" -gt 0 ]; then
        choose mode "Foundry resource" "Use an existing Foundry resource" "Create a new Foundry resource"
    fi

    if [ "$mode" = "Use an existing Foundry resource" ]; then
        choose RESOURCE "Foundry resource" "${existing[@]}"
        RESOURCE_LOCATION=$(az_sub cognitiveservices account show --name "$RESOURCE" \
            --resource-group "$GROUP" --query location --output tsv)
        if [ "$(az_sub cognitiveservices account show --name "$RESOURCE" --resource-group "$GROUP" \
            --query properties.disableLocalAuth --output tsv)" = "true" ]; then
            die "'$RESOURCE' has API key authentication turned off, which Type Fast needs. Pick or create another resource."
        fi
        return 0
    fi

    local suggested
    suggested="type-fast-$(LC_ALL=C tr -dc 'a-z0-9' </dev/urandom 2>/dev/null | head -c 6 || true)"
    say "The resource name must be globally unique; it becomes part of the endpoint URL."
    while true; do
        ask RESOURCE "New Foundry resource name" "$suggested"
        if ! valid_name "$RESOURCE"; then
            say "Use 2-64 letters, digits, and hyphens, starting and ending with a letter or digit."
            continue
        fi
        ask RESOURCE_LOCATION "Region for the Foundry resource" "${GROUP_LOCATION:-$DEFAULT_LOCATION}"
        say "Creating Foundry resource '$RESOURCE' in $RESOURCE_LOCATION (this can take a minute)..."
        if az_sub cognitiveservices account create \
            --name "$RESOURCE" \
            --resource-group "$GROUP" \
            --kind AIServices \
            --sku S0 \
            --location "$RESOURCE_LOCATION" \
            --custom-domain "$RESOURCE" \
            --assign-identity \
            --allow-project-management true \
            --output none; then
            CREATED+=("Foundry resource $RESOURCE (resource group $GROUP)")
            break
        fi
        confirm "Creating the resource failed. Try a different name or region?" y \
            || die "Couldn't create the Foundry resource."
    done

    if confirm "Also create a Foundry project named '$DEFAULT_PROJECT' for working in the Foundry portal?" y; then
        say "Creating project '$DEFAULT_PROJECT'..."
        az_sub cognitiveservices account project create \
            --name "$RESOURCE" \
            --resource-group "$GROUP" \
            --project-name "$DEFAULT_PROJECT" \
            --location "$RESOURCE_LOCATION" \
            --output none
        CREATED+=("Foundry project $DEFAULT_PROJECT (in $RESOURCE)")
    fi
}

choose_deployment() {
    heading "Model deployment"
    local existing=() mode="Deploy a new model" out
    out=$(az_sub cognitiveservices account deployment list \
        --name "$RESOURCE" --resource-group "$GROUP" \
        --query "[].[name, properties.model.name]" --output tsv) \
        || die "Couldn't list the deployments in $RESOURCE."
    lines_to_array existing <<<"$(printf '%s\n' "$out" | awk -F'\t' 'NF {print $1 " (model: " $2 ")"}')"

    if [ "${#existing[@]}" -gt 0 ]; then
        choose mode "Model deployment" "Use an existing deployment" "Deploy a new model"
    fi

    if [ "$mode" = "Use an existing deployment" ]; then
        local choice
        choose choice "Deployment" "${existing[@]}"
        DEPLOYMENT=${choice%% (model: *}
        return 0
    fi

    local model sku capacity version
    say "Type Fast works best with a small, fast model. See 'Cost tips' in docs/foundry-setup.md."
    while true; do
        ask model "Model" "$DEFAULT_MODEL"
        ask sku "Deployment type (GlobalStandard, DataZoneStandard, or Standard)" "$DEFAULT_SKU"
        version=$(az_sub cognitiveservices model list --location "$RESOURCE_LOCATION" \
            --query "[?model.format=='OpenAI' && model.name=='$model' && contains(model.skus[].name || \`[]\`, '$sku')].model.version" \
            --output tsv | sort -u | tail -n 1)
        if [ -n "$version" ]; then
            break
        fi
        say "'$model' isn't available as $sku in $RESOURCE_LOCATION. Try another model or deployment type."
    done

    while true; do
        ask DEPLOYMENT "Deployment name" "$model"
        valid_deployment_name "$DEPLOYMENT" && break
        say "Use letters, digits, periods, hyphens, and underscores, starting and ending with a letter or digit."
    done
    while true; do
        ask capacity "Capacity, in thousands of tokens per minute" "$DEFAULT_CAPACITY"
        case "$capacity" in
            '' | *[!0-9]* | 0) say "Enter a whole number greater than 0." ;;
            *) break ;;
        esac
    done

    say "Deploying $model version $version as '$DEPLOYMENT' ($sku, ${capacity}K TPM)..."
    az_sub cognitiveservices account deployment create \
        --name "$RESOURCE" \
        --resource-group "$GROUP" \
        --deployment-name "$DEPLOYMENT" \
        --model-name "$model" \
        --model-version "$version" \
        --model-format OpenAI \
        --sku-name "$sku" \
        --sku-capacity "$capacity" \
        --output none \
        || die "The deployment failed. If the error mentions quota, lower the capacity or free up quota (see 'Quota' in docs/foundry-setup.md)."
    CREATED+=("model deployment $DEPLOYMENT (in $RESOURCE)")
}

save_config() {
    heading "Configuring Type Fast"
    ENDPOINT=$(az_sub cognitiveservices account show --name "$RESOURCE" --resource-group "$GROUP" \
        --query 'properties.endpoints."AI Foundry API" || properties.endpoint' --output tsv)
    [ -n "$ENDPOINT" ] || die "Couldn't read the endpoint for '$RESOURCE'."
    ENDPOINT=${ENDPOINT%/}

    local file existing=()
    for file in azure_ai_endpoint azure_ai_api_key azure_ai_model; do
        if [ -s "$CONFIG_DIR/$file" ]; then
            existing+=("$file")
        fi
    done
    if [ "${#existing[@]}" -gt 0 ]; then
        say "Type Fast already has Foundry settings in $CONFIG_DIR (${existing[*]})."
        confirm "Replace them?" y || die "Left your existing settings unchanged."
    fi

    KEY=$(az_sub cognitiveservices account keys list --name "$RESOURCE" --resource-group "$GROUP" \
        --query key1 --output tsv) || die "Couldn't read the API key for '$RESOURCE'."
    [ -n "$KEY" ] || die "Couldn't read the API key for '$RESOURCE'."

    mkdir -p "$CONFIG_DIR"
    (umask 077 && touch "$CONFIG_DIR/azure_ai_api_key")
    chmod 600 "$CONFIG_DIR/azure_ai_api_key"
    printf '%s\n' "$KEY" >"$CONFIG_DIR/azure_ai_api_key"
    printf '%s\n' "$ENDPOINT" >"$CONFIG_DIR/azure_ai_endpoint"
    printf '%s\n' "$DEPLOYMENT" >"$CONFIG_DIR/azure_ai_model"
    printf 'azure\n' >"$CONFIG_DIR/provider"
    say "Saved the endpoint, API key, and deployment name to $CONFIG_DIR,"
    say "and chose Azure AI Foundry as Type Fast's provider."
}

test_connection() {
    heading "Testing the connection"
    local body response status attempt
    body=$(printf '{"model":"%s","input":"Reply with OK.","max_output_tokens":16}' "$DEPLOYMENT")
    response=$(mktemp)
    for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
        # Pass the key to curl on stdin so it never appears in the process list.
        status=$(printf 'header = "api-key: %s"\n' "$KEY" | curl --silent --show-error \
            --config - \
            --header 'Content-Type: application/json' \
            --data "$body" \
            --output "$response" \
            --write-out '%{http_code}' \
            --max-time 60 \
            "$ENDPOINT/openai/v1/responses") || status="000"
        if [ "$status" = "404" ] && grep -q 'DeploymentNotFound' "$response" && [ "$attempt" -lt 12 ]; then
            say "The deployment isn't ready yet; retrying in 10 seconds..."
            sleep 10
            continue
        fi
        break
    done
    KEY=""

    if [ "$status" = "200" ]; then
        say "Success: '$DEPLOYMENT' answered."
        rm -f "$response"
        return 0
    fi
    warn "The test request failed with HTTP $status:"
    sed 's/^/  /' "$response" >&2
    printf '\n' >&2
    rm -f "$response"
    warn "Your settings were saved. See 'Troubleshooting' in docs/foundry-setup.md."
    return 1
}

summary() {
    local test_ok=$1 var
    heading "Done"
    say "Endpoint:   $ENDPOINT"
    say "Deployment: $DEPLOYMENT"
    say "Settings:   $CONFIG_DIR/azure_ai_endpoint, azure_ai_api_key, azure_ai_model, provider"
    for var in AZURE_AI_ENDPOINT AZURE_AI_API_KEY AZURE_AI_MODEL; do
        if [ -n "${!var-}" ]; then
            warn "$var is set in this shell. It overrides the saved setting when you start Type Fast from this shell."
        fi
    done
    say ""
    say "Open Type Fast, or switch to it if it's running. The bottom of the window"
    say "should read 'Azure · $DEPLOYMENT', and Settings › Provider should have"
    say "Azure AI Foundry checked."
    [ "$test_ok" = "yes" ] || exit 1
}

main() {
    case "${1-}" in
        -h | --help)
            usage
            exit 0
            ;;
        '') ;;
        *) die "Unknown option '$1'. Run with --help for usage." ;;
    esac

    say "This script sets up Microsoft Foundry for Type Fast. Press Return to accept"
    say "the [default] answer, or Ctrl-C to stop at any time."

    check_prerequisites
    choose_subscription
    choose_resource_group
    choose_resource
    choose_deployment
    save_config
    # Everything is configured now, so a failed test shouldn't list resources to clean up.
    CREATED=()
    local test_ok=yes
    test_connection || test_ok=no
    summary "$test_ok"
}

main "$@"
