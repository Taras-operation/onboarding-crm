import re
from collections import defaultdict
from markupsafe import Markup

# ✅ Основний парсер форми шаблону
def parse_nested_structure(form_data):
    blocks = defaultdict(lambda: {
        "type": "stage",
        "title": "",
        "description": "",
        "subblocks": [],
        "test": {"questions": []}
    })

    for key in form_data:
        if key.startswith("blocks["):
            parts = key.split("][")
            parts = [p.replace("blocks[", "").replace("]", "") for p in parts]

            try:
                block_index = int(parts[0])
            except:
                continue

            if len(parts) == 2:
                field = parts[1]
                if field == 'title':
                    blocks[block_index]['title'] = form_data[key]
                elif field == 'description':
                    blocks[block_index]['description'] = form_data[key]

            elif len(parts) == 4 and parts[1] == 'subblocks':
                sub_index = int(parts[2])
                field = parts[3]
                while len(blocks[block_index]['subblocks']) <= sub_index:
                    blocks[block_index]['subblocks'].append({})
                blocks[block_index]['subblocks'][sub_index][field] = form_data[key]

            elif len(parts) == 4 and parts[1] == 'tests':
                test_index = int(parts[2])
                field = parts[3]
                while len(blocks[block_index]['test']['questions']) <= test_index:
                    blocks[block_index]['test']['questions'].append({"question": "", "answers": []})
                if field == 'question':
                    blocks[block_index]['test']['questions'][test_index]['question'] = form_data[key]

            elif len(parts) == 6 and parts[1] == 'tests' and parts[3] == 'answers':
                test_index = int(parts[2])
                answer_index = int(parts[4])
                field = parts[5]

                while len(blocks[block_index]['test']['questions']) <= test_index:
                    blocks[block_index]['test']['questions'][test_index]['answers'].append({"value": "", "correct": False})
                while len(blocks[block_index]['test']['questions'][test_index]['answers']) <= answer_index:
                    blocks[block_index]['test']['questions'][test_index]['answers'].append({})

                if field == 'value':
                    blocks[block_index]['test']['questions'][test_index]['answers'][answer_index]['value'] = form_data[key]
                elif field == 'correct':
                    blocks[block_index]['test']['questions'][test_index]['answers'][answer_index]['correct'] = True

    structure = [blocks[i] for i in sorted(blocks.keys())]
    return structure

# ✅ Автоматичне перетворення URL у гіперпосилання
def auto_link_urls(text):
    url_pattern = re.compile(r'(https?://[^\s]+)', re.IGNORECASE)
    return Markup(url_pattern.sub(
        r'<a href="\1" target="_blank" class="text-blue-600 underline">\1</a>', text))

# ✅ Реєстрація фільтрів для Jinja2
def register_custom_filters(app):
    def regex_replace(s, find, replace):
        return re.sub(find, replace, s)

    app.jinja_env.filters['regex_replace'] = regex_replace
    app.jinja_env.filters['autolink'] = auto_link_urls