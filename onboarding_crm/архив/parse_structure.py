import re
from collections import defaultdict

def parse_nested_structure(form_data):
    result = {}

    pattern = re.compile(r'([^\[\]]+)|\[(\d+)\]')

    for full_key in form_data:
        parts = pattern.findall(full_key)
        keys = [key if key else int(index) for key, index in parts]
        value = form_data[full_key]

        current = result
        for i, key in enumerate(keys):
            if i == len(keys) - 1:
                current[key] = value
            else:
                if isinstance(key, int):
                    if key not in current:
                        current[key] = {}
                    current = current[key]
                else:
                    if key not in current:
                        current[key] = {}
                    current = current[key]

    # Перетворити верхній рівень blocks з dict у list
    blocks = result.get("blocks", {})
    if isinstance(blocks, dict):
        result["blocks"] = [blocks[i] for i in sorted(blocks)]

    return result["blocks"]