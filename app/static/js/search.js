document.addEventListener('DOMContentLoaded', function () {
    const productSearch = document.getElementById('productSearch');
    if (productSearch) {
        productSearch.addEventListener('keyup', function () {
            let filter = productSearch.value.toUpperCase();
            let productList = document.querySelector('.product-list-body');
            let rows = productList.getElementsByClassName('product-list-row');

            for (let i = 0; i < rows.length; i++) {
                let cells = rows[i].getElementsByTagName('div');
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
                    rows[i].style.display = "grid";
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
            let packagingList = document.querySelector('.packaging-overview-body');
            let rows = packagingList.getElementsByClassName('packaging-row');

            for (let i = 0; i < rows.length; i++) {
                let cells = rows[i].getElementsByTagName('div');
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
                    rows[i].style.display = "grid";
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
            let rows = partnerList.getElementsByClassName('product-list-row');

            for (let i = 0; i < rows.length; i++) {
                let cells = rows[i].getElementsByTagName('div');
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
                    rows[i].style.display = "grid";
                } else {
                    rows[i].style.display = "none";
                }
            }
        });
    }
});