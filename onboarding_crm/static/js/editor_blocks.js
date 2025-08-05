let blockCounter = 0;

// === ДОДАТИ ЕТАП ===
function addStage(data = {}, index = null) {
  const container = document.getElementById('blocks-container');
  const blockIndex = index !== null && index !== undefined ? index : blockCounter++;

  const block = document.createElement('div');
  block.className = "bg-white p-4 rounded shadow mb-4 border relative";
  block.innerHTML = `
    <button type="button" class="absolute top-2 right-2 text-red-500 hover:text-red-700 text-xl" onclick="this.closest('div').remove()">✖</button>
    <h3 class="text-lg font-bold mb-2">Блок №${blockIndex + 1}</h3>
    <input type="text" name="blocks[${blockIndex}][title]" placeholder="Заголовок етапу" value="${data.title || ''}" class="w-full border p-2 rounded mb-2">
    <textarea name="blocks[${blockIndex}][description]" placeholder="Опис етапу" class="w-full border p-2 rounded mb-2">${data.description || ''}</textarea>

    <div class="subblocks mb-2"></div>
    <button type="button" onclick="addSubblock(this, ${blockIndex})" class="bg-blue-100 text-blue-700 px-2 py-1 rounded text-sm mb-2">+ Сабблок</button>

    <div class="open-questions mb-2"></div>
    <button type="button" onclick="addOpenQuestion(this, ${blockIndex})" class="bg-purple-100 text-purple-700 px-2 py-1 rounded text-sm mb-2">+ Відкрите питання</button>

    <div class="tests"></div>
    <button type="button" onclick="addTest(this, ${blockIndex})" class="bg-green-100 text-green-700 px-2 py-1 rounded text-sm">+ Тест</button>
  `;

  container.appendChild(block);

  // Якщо є дані
  if (data.subblocks) {
    data.subblocks.forEach((sb, sbIndex) => addSubblock(block.querySelector('.subblocks'), blockIndex, sbIndex, sb));
  }
  if (data.open_questions) {
    data.open_questions.forEach((oq, oqIndex) => addOpenQuestion(block.querySelector('.open-questions'), blockIndex, oqIndex, oq));
  }
  if (data.test) {
    addTest(block.querySelector('.tests'), blockIndex, data.test);
  }
}

// === ДОДАТИ САББЛОК ===
function addSubblock(parentEl, blockIndex, subIndex = null, data = {}) {
  const container = typeof parentEl === 'object' && parentEl.classList?.contains('subblocks')
    ? parentEl
    : parentEl.previousElementSibling;

  const subblocks = container.querySelectorAll('.subblock');
  const idx = subIndex !== null ? subIndex : subblocks.length;

  const div = document.createElement('div');
  div.className = "subblock border p-2 mb-2 rounded bg-gray-50 relative";
  div.innerHTML = `
    <button type="button" class="absolute top-1 right-2 text-red-500 hover:text-red-700 text-xl" onclick="this.closest('.subblock').remove()">✖</button>
    <input type="text" name="blocks[${blockIndex}][subblocks][${idx}][title]" placeholder="Назва сабблоку" value="${data.title || ''}" class="w-full p-1 mb-1 border rounded" />
    <textarea name="blocks[${blockIndex}][subblocks][${idx}][description]" placeholder="Опис сабблоку" class="w-full p-1 border rounded">${data.description || ''}</textarea>
  `;
  container.appendChild(div);
}

// === ДОДАТИ ВІДКРИТЕ ПИТАННЯ ===
function addOpenQuestion(parentEl, blockIndex, openIndex = null, data = {}) {
  const container = typeof parentEl === 'object' && parentEl.classList?.contains('open-questions')
    ? parentEl
    : parentEl.previousElementSibling;

  const openQuestions = container.querySelectorAll('.open-question');
  const idx = openIndex !== null ? openIndex : openQuestions.length;

  const div = document.createElement('div');
  div.className = "open-question border p-2 mb-2 rounded bg-purple-50 relative";
  div.innerHTML = `
    <button type="button" class="absolute top-1 right-2 text-red-500 hover:text-red-700 text-xl" onclick="this.closest('.open-question').remove()">✖</button>
    <input type="text" name="blocks[${blockIndex}][open_questions][${idx}][question]" placeholder="Відкрите питання" value="${data.question || ''}" class="w-full p-1 mb-1 border rounded" />
  `;
  container.appendChild(div);
}

// === ДОДАТИ ТЕСТ ===
function addTest(parentEl, blockIndex, data = {}) {
  const container = typeof parentEl === 'object' && parentEl.classList?.contains('tests')
    ? parentEl
    : parentEl.previousElementSibling;

  const div = document.createElement('div');
  div.className = "test border p-2 mb-2 rounded bg-green-50 relative";
  div.innerHTML = `
    <button type="button" class="absolute top-1 right-2 text-red-500 hover:text-red-700 text-xl" onclick="this.closest('.test').remove()">✖</button>
    <input type="text" name="blocks[${blockIndex}][test][question]" placeholder="Питання" value="${data.question || ''}" class="w-full p-1 mb-1 border rounded" />
    <div class="answers"></div>
    <button type="button" onclick="addAnswer(this)" class="bg-green-100 text-green-700 px-2 py-1 rounded text-sm">+ Відповідь</button>
  `;

  container.appendChild(div);

  if (data.answers) {
    const answersContainer = div.querySelector('.answers');
    data.answers.forEach((a, idx) => addAnswer(answersContainer, idx, a));
  }
}

// === ДОДАТИ ВІДПОВІДЬ ДО ТЕСТУ ===
function addAnswer(parentEl, index = null, data = {}) {
  const container = typeof parentEl === 'object' && parentEl.classList?.contains('answers')
    ? parentEl
    : parentEl.previousElementSibling;

  const answers = container.querySelectorAll('.answer');
  const idx = index !== null ? index : answers.length;

  const div = document.createElement('div');
  div.className = "answer flex items-center gap-2 mb-1";
  div.innerHTML = `
    <input type="text" name="answer_${idx}" placeholder="Відповідь" value="${data.value || ''}" class="flex-1 p-1 border rounded" />
    <label class="flex items-center gap-1">
      <input type="checkbox" ${data.correct ? 'checked' : ''} /> Правильна
    </label>
    <button type="button" onclick="this.closest('.answer').remove()" class="text-red-500 hover:underline">✖</button>
  `;
  container.appendChild(div);
}

// === ЗБЕРЕГТИ СТРУКТУРУ ===
function parseStructure() {
  const blocks = [];
  document.querySelectorAll('#blocks-container > div').forEach((blockDiv, i) => {
    const block = {
      title: blockDiv.querySelector(`[name="blocks[${i}][title]"]`)?.value || '',
      description: blockDiv.querySelector(`[name="blocks[${i}][description]"]`)?.value || '',
      subblocks: [],
      open_questions: [],
      test: { questions: [] }
    };

    blockDiv.querySelectorAll('.subblock').forEach((sbDiv) => {
      block.subblocks.push({
        title: sbDiv.querySelector(`[name^="blocks[${i}][subblocks]"][name$="[title]"]`)?.value || '',
        description: sbDiv.querySelector(`[name^="blocks[${i}][subblocks]"][name$="[description]"]`)?.value || ''
      });
    });

    blockDiv.querySelectorAll('.open-question').forEach((oqDiv) => {
      block.open_questions.push({
        question: oqDiv.querySelector(`[name^="blocks[${i}][open_questions]"][name$="[question]"]`)?.value || ''
      });
    });

    blockDiv.querySelectorAll('.test').forEach((testDiv) => {
      const question = testDiv.querySelector(`[name^="blocks[${i}][test][question]"]`)?.value || '';
      const answers = [];
      testDiv.querySelectorAll('.answer').forEach((aDiv) => {
        answers.push({
          value: aDiv.querySelector('input[type="text"]')?.value || '',
          correct: aDiv.querySelector('input[type="checkbox"]')?.checked || false
        });
      });
      block.test.questions.push({ question, answers });
    });

    blocks.push(block);
  });
  document.getElementById('structure').value = JSON.stringify(blocks);
  return blocks;
}

// === АВТОЗБЕРЕЖЕННЯ ===
function autosaveTemplate() {
  if (!window.templateId) return;
  const structure = parseStructure();
  fetch(`/autosave_template/${window.templateId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ structure })
  }).then(res => res.json())
    .then(data => console.log("Автозбереження:", data))
    .catch(err => console.error("Помилка автозбереження:", err));
}

document.querySelector('form').addEventListener('submit', () => parseStructure());

// Ініціалізація
if (window.templateData && window.templateData.length) {
  window.templateData.forEach((block, i) => addStage(block, i));
}