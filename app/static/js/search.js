document.addEventListener('DOMContentLoaded', function () {
    const productSearch = document.getElementById('productSearch');
    if (productSearch) {
        productSearch.addEventListener('keyup', function () {
            let filter = productSearch.value.toUpperCase();
            let productList = document.getElementById('product-list-body');
            let rows = productList.querySelectorAll('.product-list-row');

            for (let i = 0; i < rows.length; i++) {
                let cells = rows[i].children;
                let match = false;
                for (let j = 0; j < cells.length; j++) {
                    if (cells[j]) {
                        if (cells[j].innerText.toUpperCase().indexOf(filter) > -1) {
                            match = true;
                            break;
                        }
                    }
                }
                if (match) {
                    rows[i].style.display = "";
                } else {
                    rows[i].style.display = "none";
                }
            }
        });
    }

    const packagingSearch = document.getElementById('packagingSearch');
    if (packagingSearch) {
        packagingSearch.addEventListener('keyup', function () {
            let filter = packagingSearch.value.toUpperCase();
            let packagingList = document.getElementById('packaging-list-body');
            let rows = packagingList.querySelectorAll('.packaging-row');

            for (let i = 0; i < rows.length; i++) {
                let cells = rows[i].children;
                let match = false;
                for (let j = 0; j < cells.length; j++) {
                    if (cells[j]) {
                        if (cells[j].innerText.toUpperCase().indexOf(filter) > -1) {
                            match = true;
                            break;
                        }
                    }
                }
                if (match) {
                    rows[i].style.display = "";
                } else {
                    rows[i].style.display = "none";
                }
            }
        });
    }

    const partnerSearch = document.getElementById('partnerSearch');
    if (partnerSearch) {
        partnerSearch.addEventListener('keyup', function () {
            let filter = partnerSearch.value.toUpperCase();
            let partnerList = document.getElementById('partner-list-body');
            let rows = partnerList.querySelectorAll('.product-list-row');

            for (let i = 0; i < rows.length; i++) {
                let cells = rows[i].children;
                let match = false;
                for (let j = 0; j < cells.length; j++) {
                    if (cells[j]) {
                        if (cells[j].innerText.toUpperCase().indexOf(filter) > -1) {
                            match = true;
                            break;
                        }
                    }
                }
                if (match) {
                    rows[i].style.display = "";
                } else {
                    rows[i].style.display = "none";
                }
            }
        });
    }
});