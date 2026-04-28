from mcp.server.fastmcp import FastMCP, Image, Context
import json
import urllib
from urllib import request
import time
import os
import random
import copy
from langchain_ollama.chat_models import ChatOllama
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

mcp = FastMCP("Comfy MCP Server")

host = os.environ.get("COMFY_URL")
override_host = os.environ.get("COMFY_URL_EXTERNAL")
if override_host is None:
    override_host = host
output_mode = os.environ.get("OUTPUT_MODE")
comfy_timeout = int(os.environ.get("COMFY_TIMEOUT", "120"))

ollama_api_base = os.environ.get("OLLAMA_API_BASE")
prompt_llm = os.environ.get("PROMPT_LLM")

workflow_index_file = os.environ.get("COMFY_WORKFLOW_INDEX")
workflows = {}
ollama_prompt_template = None

if workflow_index_file is not None:
    index_dir = os.path.dirname(os.path.abspath(workflow_index_file))
    with open(workflow_index_file, "r") as f:
        index = json.load(f)
    ollama_prompt_template = index.get("prompt_template")
    for entry in index.get("workflows", []):
        workflow_path = os.path.join(index_dir, entry["file"])
        with open(workflow_path, "r") as f:
            template = json.load(f)
        workflows[entry["name"]] = {
            "description": entry.get("description", entry["name"]),
            "nodes": entry.get("nodes", {}),
            "template": template,
        }


def get_file_url(server: str, url_values: str) -> str:
    return f"{server}/view?{url_values}"


def find_node_by_class(template: dict, class_type: str) -> str | None:
    for node_id, node in template.items():
        if node.get("class_type") == class_type:
            return node_id
    return None


def find_prompt_nodes(template: dict) -> tuple[str | None, str | None]:
    """Follow a KSampler's positive/negative connections to find the prompt node IDs."""
    for node in template.values():
        if node.get("class_type") in ("KSampler", "KSamplerAdvanced"):
            inputs = node.get("inputs", {})
            positive = inputs.get("positive")
            negative = inputs.get("negative")
            pos_id = positive[0] if isinstance(positive, list) else None
            neg_id = negative[0] if isinstance(negative, list) else None
            return pos_id, neg_id
    return None, None


def get_positive_node_id(template: dict, overrides: dict) -> str | None:
    if "positive_prompt" in overrides:
        return overrides["positive_prompt"]
    pos_id, _ = find_prompt_nodes(template)
    return pos_id


def get_negative_node_id(template: dict, overrides: dict) -> str | None:
    if "negative_prompt" in overrides:
        return overrides["negative_prompt"]
    _, neg_id = find_prompt_nodes(template)
    return neg_id


def get_output_node_id(template: dict, overrides: dict) -> str | None:
    if "output" in overrides:
        return overrides["output"]
    return find_node_by_class(template, "SaveImage")


if ollama_api_base is not None and prompt_llm is not None:
    @mcp.tool()
    def generate_prompt(topic: str, ctx: Context) -> str:
        """Write an image generation prompt for a provided topic"""

        model = ChatOllama(base_url=ollama_api_base, model=prompt_llm)
        default_template = """You are an AI Image Generation Prompt Assistant.
        Your job is to review the topic provided by the user and create appropriate image generation prompts.
        Respond with exactly two lines in this format:
        Positive: <comma-separated descriptive tags and style keywords for what should appear in the image>
        Negative: <comma-separated tags for what should be excluded from the image>
        Do not include any other text or explanation.

        Topic: {topic}
        """
        prompt = PromptTemplate.from_template(ollama_prompt_template or default_template)
        chain = prompt | model | StrOutputParser()
        response = chain.invoke({"topic": topic})
        return response


@mcp.tool()
def list_workflows() -> str:
    """List available ComfyUI workflows"""
    if not workflows:
        return "No workflows available."
    lines = [f"- {name}: {info['description']}" for name, info in workflows.items()]
    return "\n".join(lines)


@mcp.tool()
def generate_image(
    prompt: str,
    ctx: Context,
    workflow_name: str = None,
    negative_prompt: str = None,
    seed: int = None,
):
    """Generate an image using a ComfyUI workflow. Call list_workflows first to see available options.
    Omit workflow_name to use the default workflow.
    Omit seed to generate a random variation each time, or provide a specific seed to reproduce a previous result.
    After the image is returned, display it inline to the user using markdown image syntax and then stop."""

    if not workflows:
        return "No workflows available."

    if workflow_name is None:
        workflow_name = next(iter(workflows))

    if workflow_name not in workflows:
        available = ", ".join(workflows.keys())
        return f"Workflow '{workflow_name}' not found. Available workflows: {available}"

    workflow_info = workflows[workflow_name]
    template = copy.deepcopy(workflow_info["template"])
    overrides = workflow_info["nodes"]

    pos_node_id = get_positive_node_id(template, overrides)
    if pos_node_id is None:
        return "Could not find positive prompt node. Add a 'positive_prompt' node override to index.json."
    template[pos_node_id]["inputs"]["text"] = prompt

    if negative_prompt is not None:
        neg_node_id = get_negative_node_id(template, overrides)
        if neg_node_id is not None:
            template[neg_node_id]["inputs"]["text"] = negative_prompt

    for node in template.values():
        if "seed" in node.get("inputs", {}):
            node["inputs"]["seed"] = seed if seed is not None else random.randint(0, 0xffffffffffffffff)

    out_node_id = get_output_node_id(template, overrides)
    if out_node_id is None:
        return "Could not find output node. Add an 'output' node override to index.json."

    p = {"prompt": template}
    data = json.dumps(p).encode("utf-8")
    req = request.Request(f"{host}/prompt", data)
    resp = request.urlopen(req)
    response_ready = False
    if resp.status == 200:
        ctx.info("Submitted prompt")
        resp_data = json.loads(resp.read())
        prompt_id = resp_data["prompt_id"]

        for _ in range(0, comfy_timeout):
            history_req = request.Request(f"{host}/history/{prompt_id}")
            history_resp = request.urlopen(history_req)
            if history_resp.status == 200:
                ctx.info("Checking status...")
                history_resp_data = json.loads(history_resp.read())
                if prompt_id in history_resp_data:
                    status = history_resp_data[prompt_id]["status"]["completed"]
                    if status:
                        output_data = (
                            history_resp_data[prompt_id]
                            ["outputs"][out_node_id]["images"][0]
                        )
                        url_values = urllib.parse.urlencode(output_data)
                        file_url = get_file_url(host, url_values)
                        override_file_url = get_file_url(override_host, url_values)
                        file_req = request.Request(file_url)
                        file_resp = request.urlopen(file_req)
                        if file_resp.status == 200:
                            ctx.info("Image generated")
                            output_file = file_resp.read()
                            response_ready = True
                        break
                    else:
                        time.sleep(1)
                else:
                    time.sleep(1)

    if response_ready:
        if output_mode is not None and output_mode.lower() == "url":
            return override_file_url
        return Image(data=output_file, format="png")
    else:
        return "Failed to generate image. Please check server logs."


def run_server():
    errors = []
    if host is None:
        errors.append("- COMFY_URL environment variable not set")
    if workflow_index_file is None:
        errors.append("- COMFY_WORKFLOW_INDEX environment variable not set")
    elif not workflows:
        errors.append("- No workflows loaded from COMFY_WORKFLOW_INDEX")

    if errors:
        return "\n".join(["Failed to start Comfy MCP Server:"] + errors)
    mcp.run()


if __name__ == "__main__":
    run_server()
