import os

# Must be set before litellm is imported anywhere — prevents slow remote fetch
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("LITELLM_LOG", "ERROR")

__version__ = "0.1.0"
