document.addEventListener("DOMContentLoaded", function () {
    let stepCount = 0;

    const stepsContainer = document.getElementById("steps-container");

    // Добавить этап
    document.getElementById("add-step").addEventListener("click", function () {
        stepCount++;
        const stepBlock = document.createElement("div");
        stepBlock.classList.add("step-block", "p-3", "mb-3", "border", "rounded");
        stepBlock.innerHTML = `
            <h5>Етап ${stepCount}</h5>
            <input id="step-input-${stepCount}" type="hidden" name="steps[]" />
            <trix-editor input="step-input-${stepCount}"></trix-editor>
            <button type="button" class="btn btn-danger mt-2 remove-step">🗑 Видалити</button>
        `;
        stepsContainer.appendChild(stepBlock);
    });

    // Удалить этап
    stepsContainer.addEventListener("click", function (e) {
        if (e.target && e.target.classList.contains("remove-step")) {
            e.target.closest(".step-block").remove();
        }
    });
});