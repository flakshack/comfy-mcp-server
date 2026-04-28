# Comfy MCP Server

> A server using the FastMCP framework to generate images via a remote ComfyUI server.

## Overview

Comfy MCP Server connects AI assistants (such as LM Studio or Claude Desktop) to a remote ComfyUI instance via the Model Context Protocol (MCP). It exposes tools for listing available (exported) workflows and generating images, with support for runtime control of prompts and seeds.

Workflow JSON files are used as exported directly from ComfyUI — no manual editing required. A simple index file is used to register workflows, provide AI-friendly descriptions so it can decide which workflow to use for your image based on context,
and prompt suggestions for each specific workflow.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) package and project manager for Python
- A running [ComfyUI](https://github.com/comfyanonymous/ComfyUI) instance accessible over the network
- One or more workflow JSON files exported from ComfyUI

## Setup

### 1. Create a workflows folder

On the computer running your AI assistant (not the remote computer running ComfyUI), create a folder to store your workflow files, for example `/path/to/workflows/`.

### 2. Export a ComfyUI workflow

Export ComfyUI workflows directly from the ComfyUI web UI and place them in this folder on the computer running LM Studio or Claude. Ensure that your workflows work properly in ComfyUI first; the example files use native ComfyUI models, so they should work unchanged. In ComfyUI, right-click on the workflow tab and choose "Export (API)."  You may need to enable Developer Mode in settings before this option will appear.

### 3. Create an index.json file

Create an `index.json` file in the same folder. This is the only file you need to edit manually.

```json
{
  "workflows": [
    {
      "name": "my-workflow",
      "description": "A clear description that helps the AI choose the right workflow.",
      "file": "my-workflow.json"
    },
    {
      "name": "another-workflow",
      "description": "Another workflow for a different style or purpose."
    }
  ]
}
```

The `name` is used to select the workflow at runtime. The `description` is shown to the AI so it can pick the most appropriate workflow for the user's request. Other optional fields are explained below.

### Example workflows folder

> The `workflows-example/` folder contains two ready-to-use workflows and a matching `index.json` that should work without any special models or configurations in ComfyUI. Copy this folder as a starting point and add your own workflows alongside it.

#### Supported workflow types

This Comfy MCP Server automatically detects nodes by traversing the workflow graph to determine where to insert prompts and other settings (like a random seed). The following workflow architectures are included in the `workflows-example` folder:

| Architecture | Sampler node | Negative prompt |
|---|---|---|
| SD 1.5 / SDXL | `KSampler` or `KSamplerAdvanced` | Supported |
| Flux | `SamplerCustomAdvanced` | Not used (Flux does not support negative prompts) |

Workflows using other advanced or custom node structures may require node overrides (see below). Note that this code needs to understand nodes so it will know where to update prompts and seeds, so for example, an audio or video workflow would likely not work without some modification of the code.

#### Optional: disabling workflows

Set `"enabled": false` on any workflow entry to exclude it from the server without removing it from the index. Omitting the field is the same as `true`. This is useful for keeping workflows in the index for reference while only exposing the ones that are ready to use.

```json
{
  "workflows": [
    {
      "name": "image-basic",
      "description": "Works out of the box.",
      "file": "image-basic.json"
    },
    {
      "name": "image-custom",
      "description": "Requires additional models.",
      "file": "image-custom.json",
      "enabled": false
    }
  ]
}
```

Use this to keep additional workflows in the index for reference without exposing them to the AI until they are ready to use.

#### Optional: node overrides

Comfy MCP Server automatically detects the positive prompt, negative prompt, and output nodes in your workflow by traversing the node graph. If a workflow uses an unusual structure, you can override the detected node IDs per workflow:

```json
{
  "workflows": [
    {
      "name": "custom-workflow",
      "description": "Workflow with non-standard node wiring.",
      "file": "custom.json",
      "nodes": {
        "positive_prompt": "6",
        "negative_prompt": "7",
        "output": "25"
      }
    }
  ]
}
```

#### Optional: per-workflow prompt guidance

Different models respond better to different prompting styles — for example, Stable Diffusion works best with comma-separated tags while Flux prefers natural language. Adding a `prompt_guidance` field to a workflow entry gives the AI instructions on how to construct prompts for that specific workflow. This is shown to the AI when it calls `list_workflows`, before it writes the prompt and calls `generate_image`.

```json
{
  "workflows": [
    {
      "name": "image-anime",
      "description": "Generates an anime style image.",
      "prompt_guidance": "Use comma-separated anime-style tags. Negative prompts are supported.",
      "file": "image-anime.json"
    },
    {
      "name": "flux2",
      "description": "General purpose Flux 2 model.",
      "prompt_guidance": "Use natural language descriptions. Negative prompts are not supported.",
      "file": "image_flux2_text_to_image.json"
    }
  ]
}
```

#### Optional: custom prompt template

If you are using the optional Ollama `generate_prompt` tool, you can override the default prompt template at the top level of `index.json`. This controls how the Ollama model expands a short topic into a full image generation prompt. The `{topic}` placeholder is required.

```json
{
  "prompt_template": "You are an image prompt specialist. Given the topic below, respond with exactly two lines:\nPositive: <descriptive tags>\nNegative: <exclusion tags>\n\nTopic: {topic}\n",
  "workflows": [...]
}
```

## Configuration

Set the following environment variables:

| Variable | Required | Description |
|---|---|---|
| `COMFY_URL` | Yes | URL of your ComfyUI server, including port |
| `COMFY_WORKFLOW_INDEX` | Yes | Absolute path to your `index.json` file |
| `OUTPUT_MODE` | No | Set to `url` to return an image URL instead of binary data, for LM Studio file should return the image inline using markdown formatting.  You may need to instruct your LM Studio model to ensure it outputs the returned file using markdown formatting and models without thinking may fail to do this. |
| `COMFY_URL_EXTERNAL` | No | Public-facing URL to use when `OUTPUT_MODE=url` |
| `COMFY_TIMEOUT` | No | Seconds to wait for image generation (default: `120`) |
| `OLLAMA_API_BASE` | No | URL of an Ollama server — enables the `generate_prompt` tool |
| `PROMPT_LLM` | No | Ollama model name to use for prompt generation |

## Usage

### Running from a local clone

```bash
uvx --from /path/to/comfy-mcp-server comfy-mcp-server
```

### Example LM Studio config (mcp.json)

```json
{
  "mcpServers": {
    "comfyui": {
      "command": "uvx",
      "args": [
        "--from",
        "/path/to/comfy-mcp-server",
        "--no-cache",
        "comfy-mcp-server"
      ],
      "env": {
        "COMFY_URL": "http://your-comfy-server-url:port",
        "COMFY_WORKFLOW_INDEX": "/path/to/workflows/index.json",
        "OUTPUT_MODE": "file",
        "COMFY_TIMEOUT": "120"
      }
    }
  }
}
```

## Tools

### `list_workflows()`

Returns a list of available workflows with their descriptions. The AI should call this before `generate_image` to choose the most appropriate workflow.  Keep in mind that this is not reading workflows you may have in ComfyUI, this is reading files via the index that you have copied to the computer running LM Studio.

### `generate_image(prompt, workflow_name, negative_prompt, seed)`

Generates an image using the specified ComfyUI workflow.

| Parameter | Required | Description |
|---|---|---|
| `prompt` | Yes | The positive image generation prompt |
| `workflow_name` | No | Name of the workflow to use (defaults to the first workflow in index.json) |
| `negative_prompt` | No | Things to exclude from the image |
| `seed` | No | Omit for a random result each time, or provide a specific value to reproduce a previous image |

Positive and negative prompt nodes are detected automatically from the workflow graph. The output node is detected by finding the `SaveImage` node. Both can be overridden in `index.json` if needed.

### `generate_prompt(topic)` *(optional)*

Generates a positive and negative image generation prompt from a short topic description. Only available when `OLLAMA_API_BASE` and `PROMPT_LLM` environment variables are set.

## Dependencies

- `mcp[cli]`: FastMCP server framework
- `langchain`: LLM prompt chain for optional prompt generation
- `langchain-ollama`: Ollama integration for LangChain

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
