// Auto-import on Enter in barcode field
document.addEventListener('DOMContentLoaded', function () {
    const barcodeInput = document.querySelector('input[name="barcode"]');
    const importButton = document.querySelector('button[name="action_import_from_open_food_facts"]');

    if (barcodeInput && importButton) {
        barcodeInput.addEventListener('keydown', function (event) {
            // Trigger import on Enter key, but only if barcode field has content
            if (event.key === 'Enter') {
                event.preventDefault();
                const barcodeValue = (barcodeInput.value || '').trim();
                if (barcodeValue.length >= 3) {
                    importButton.click();
                }
            }
        });
    }
});
