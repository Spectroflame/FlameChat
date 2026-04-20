"""Pick a shortlist of Ollama models that fit the user's hardware.

A model needs roughly ``param_billions * bits_per_weight / 8`` GB of memory
for weights, plus 1-2 GB for KV cache and overhead. We use conservative
estimates so the machine does not swap under load.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .hardware import HardwareProfile


Use = Literal["chat", "coding", "multimodal", "both"]


@dataclass(frozen=True)
class ModelSuggestion:
    ollama_name: str        # what you pass to `ollama pull`
    display_name: str       # human-readable label
    size_gb: float          # approximate download size
    ram_required_gb: float  # conservative runtime memory requirement
    use_case: Use
    description: str


CATALOG: tuple[ModelSuggestion, ...] = (
    # --- Tiny — runs anywhere, even on 4 GB laptops ---
    ModelSuggestion(
        ollama_name="qwen3:1.7b",
        display_name="Qwen 3 1.7B",
        size_gb=1.4,
        ram_required_gb=3.0,
        use_case="chat",
        description="Qwen 3 tiny chat model — newer than the 2.5 series.",
    ),
    ModelSuggestion(
        ollama_name="qwen2.5-coder:1.5b",
        display_name="Qwen2.5 Coder 1.5B (Q4)",
        size_gb=1.0,
        ram_required_gb=3.0,
        use_case="coding",
        description="Very small coding model. Works on almost any machine.",
    ),
    ModelSuggestion(
        ollama_name="gemma3:1b",
        display_name="Gemma 3 1B",
        size_gb=0.8,
        ram_required_gb=2.5,
        use_case="chat",
        description="Google's tiny text-only chat model.",
    ),
    ModelSuggestion(
        ollama_name="llama3.2:1b",
        display_name="Llama 3.2 1B (Q4)",
        size_gb=1.3,
        ram_required_gb=3.0,
        use_case="chat",
        description="Tiny general-purpose chat model.",
    ),

    # --- Small — 8 GB machines ---
    ModelSuggestion(
        ollama_name="qwen3:4b",
        display_name="Qwen 3 4B",
        size_gb=2.5,
        ram_required_gb=5.0,
        use_case="chat",
        description="Qwen 3 compact chat model — strong all-rounder for 8 GB machines.",
    ),
    ModelSuggestion(
        ollama_name="qwen2.5-coder:3b",
        display_name="Qwen2.5 Coder 3B (Q4)",
        size_gb=2.0,
        ram_required_gb=5.0,
        use_case="coding",
        description="Good coding model for 8 GB laptops.",
    ),
    ModelSuggestion(
        ollama_name="llama3.2:3b",
        display_name="Llama 3.2 3B (Q4)",
        size_gb=2.0,
        ram_required_gb=5.0,
        use_case="chat",
        description="Solid general-purpose chat model.",
    ),
    ModelSuggestion(
        ollama_name="gemma3:4b",
        display_name="Gemma 3 4B",
        size_gb=3.3,
        ram_required_gb=5.5,
        use_case="multimodal",
        description="Google Gemma 3 small multimodal — chats and reads images.",
    ),

    # --- Medium — 16 GB / 8 GB VRAM ---
    ModelSuggestion(
        ollama_name="qwen3:8b",
        display_name="Qwen 3 8B",
        size_gb=5.2,
        ram_required_gb=9.0,
        use_case="chat",
        description="Qwen 3 mid-size chat — successor to Qwen 2.5 7B.",
    ),
    ModelSuggestion(
        ollama_name="qwen2.5-coder:7b",
        display_name="Qwen2.5 Coder 7B (Q4)",
        size_gb=4.7,
        ram_required_gb=8.0,
        use_case="coding",
        description="Strong coding model. Recommended on 16 GB machines.",
    ),
    ModelSuggestion(
        ollama_name="llama3.1:8b",
        display_name="Llama 3.1 8B (Q4)",
        size_gb=4.9,
        ram_required_gb=8.0,
        use_case="chat",
        description="Very capable general chat model.",
    ),
    ModelSuggestion(
        ollama_name="gemma4:e2b",
        display_name="Gemma 4 E2B",
        size_gb=7.2,
        ram_required_gb=10.0,
        use_case="multimodal",
        description="Google's newest efficient-architecture multimodal (E2B).",
    ),

    # --- Large — 24 GB unified / 16 GB VRAM ---
    ModelSuggestion(
        ollama_name="qwen3:14b",
        display_name="Qwen 3 14B",
        size_gb=9.3,
        ram_required_gb=14.0,
        use_case="chat",
        description="Qwen 3 large chat — the newer chat flagship under 16 GB.",
    ),
    ModelSuggestion(
        ollama_name="qwen2.5-coder:14b",
        display_name="Qwen2.5 Coder 14B (Q4)",
        size_gb=9.0,
        ram_required_gb=14.0,
        use_case="coding",
        description="Near-frontier coding quality. Needs 24 GB unified memory.",
    ),
    ModelSuggestion(
        ollama_name="gemma3:12b",
        display_name="Gemma 3 12B",
        size_gb=8.1,
        ram_required_gb=11.0,
        use_case="multimodal",
        description="Google Gemma 3 mid-size multimodal, strong all-rounder.",
    ),
    ModelSuggestion(
        ollama_name="gemma4:e4b",
        display_name="Gemma 4 E4B",
        size_gb=9.6,
        ram_required_gb=13.0,
        use_case="multimodal",
        description="Gemma 4 mid-size multimodal — the new E-series default.",
    ),

    # --- XL — 32 GB+ or high-end GPU ---
    ModelSuggestion(
        ollama_name="qwen3-coder:30b",
        display_name="Qwen 3 Coder 30B",
        size_gb=19.0,
        ram_required_gb=24.0,
        use_case="coding",
        description="Qwen 3 Coder — the newer coding flagship, replaces Qwen 2.5 Coder.",
    ),
    ModelSuggestion(
        ollama_name="qwen3:32b",
        display_name="Qwen 3 32B",
        size_gb=20.0,
        ram_required_gb=24.0,
        use_case="chat",
        description="Qwen 3 top-tier chat. Workstation/large-Mac territory.",
    ),
    ModelSuggestion(
        ollama_name="qwen2.5-coder:32b",
        display_name="Qwen2.5 Coder 32B (Q4)",
        size_gb=20.0,
        ram_required_gb=24.0,
        use_case="coding",
        description="Top-tier Qwen 2.5 coding model (legacy but still strong).",
    ),
    ModelSuggestion(
        ollama_name="gemma3:27b",
        display_name="Gemma 3 27B",
        size_gb=17.0,
        ram_required_gb=22.0,
        use_case="multimodal",
        description="Gemma 3 large multimodal — near-top-tier image + chat.",
    ),
    ModelSuggestion(
        ollama_name="gemma4:26b",
        display_name="Gemma 4 26B",
        size_gb=18.0,
        ram_required_gb=24.0,
        use_case="chat",
        description="Gemma 4 large — Google's newest flagship in the 26 B class.",
    ),
    ModelSuggestion(
        ollama_name="gemma4:31b",
        display_name="Gemma 4 31B",
        size_gb=20.0,
        ram_required_gb=26.0,
        use_case="multimodal",
        description="Gemma 4 31B — top-tier multimodal on workstation hardware.",
    ),

    # --- XXL — workstation class ---
    ModelSuggestion(
        ollama_name="llama3.3:70b",
        display_name="Llama 3.3 70B (Q4)",
        size_gb=43.0,
        ram_required_gb=48.0,
        use_case="chat",
        description="Frontier-class open model. Workstation hardware only.",
    ),
)


def recommend(profile: HardwareProfile, *, limit: int = 4) -> list[ModelSuggestion]:
    """Return the models that realistically run on this machine, best-first.

    "Best" = largest ram_required that still fits the budget, with at most
    one coding + one chat model per tier for variety.
    """
    budget = profile.effective_vram_gb
    fitting = [m for m in CATALOG if m.ram_required_gb <= budget + 0.5]
    if not fitting:
        # Hardware below our smallest entry — still return the smallest so the
        # user has something to try, with a warning surfaced by the UI.
        fitting = [min(CATALOG, key=lambda m: m.ram_required_gb)]
    fitting.sort(key=lambda m: m.ram_required_gb, reverse=True)

    seen_combos: set[tuple[str, str]] = set()
    picked: list[ModelSuggestion] = []
    for m in fitting:
        tier = _tier(m.ram_required_gb)
        key = (tier, m.use_case)
        if key in seen_combos:
            continue
        seen_combos.add(key)
        picked.append(m)
        if len(picked) >= limit:
            break
    return picked


def _tier(ram_gb: float) -> str:
    if ram_gb < 4:
        return "tiny"
    if ram_gb < 7:
        return "small"
    if ram_gb < 12:
        return "medium"
    if ram_gb < 20:
        return "large"
    return "xl"
