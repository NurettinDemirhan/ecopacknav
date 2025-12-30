// app/static/js/product_sales.js

let currentProductSalesId = null;
let currentProductSalesEditIndex = null;
let currentProductSalesData = [];

// Helper to get month name
const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"
];

function renderProductSalesRows(sales) {
  const tbody = document.getElementById("productSalesTableBody");
  if (!tbody) return;

  currentProductSalesData = sales || [];
  tbody.innerHTML = "";

  (sales || []).forEach((sale, index) => {
    const tr = document.createElement("tr");
    const isEditing = index === currentProductSalesEditIndex;

    const monthName = sale.month ? MONTHS[parseInt(sale.month, 10) - 1] : "";

    if (isEditing) {
      tr.innerHTML = `
        <td><input type="number" class="form-control form-control-sm edit-year" value="${sale.year ?? ""}"></td>
        <td><input type="number" class="form-control form-control-sm edit-month" value="${sale.month ?? ""}" min="1" max="12"></td>
        <td><input type="number" class="form-control form-control-sm edit-qty" value="${sale.quantity ?? ""}"></td>
        <td><input type="number" step="0.01" class="form-control form-control-sm edit-sku" value="${sale.sku_price ?? ""}"></td>
        <td class="d-flex">
          <button class="btn btn-sm btn-success me-2 product-sale-save" data-index="${index}">Save</button>
          <button class="btn btn-sm btn-secondary me-2 product-sale-cancel">Cancel</button>
          <button class="btn btn-sm btn-danger product-sale-delete" data-index="${index}">Delete</button>
        </td>
      `;
    } else {
      tr.innerHTML = `
        <td>${sale.year ?? ""}</td>
        <td>${monthName}</td>
        <td>${sale.quantity ?? ""}</td>
        <td>${sale.sku_price ?? "—"}</td>
        <td>
          <button class="btn btn-sm btn-outline-secondary me-2 product-sale-edit" data-index="${index}">Edit</button>
          <button class="btn btn-sm btn-danger product-sale-delete" data-index="${index}">Delete</button>
        </td>
      `;
    }

    tbody.appendChild(tr);
  });
}

async function fetchSales(productId) {
  const res = await fetch(`/get_product_sales/${productId}`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.sales || [];
}

function populateYearDropdown() {
  const yearSelect = document.getElementById("productSalesYear");
  if (!yearSelect) return;

  const currentYear = new Date().getFullYear();
  const startYear = currentYear - 10;
  const endYear = currentYear + 10;

  yearSelect.innerHTML = "";
  for (let year = endYear; year >= startYear; year--) {
    const option = document.createElement("option");
    option.value = year;
    option.textContent = year;
    if (year === currentYear) {
      option.selected = true;
    }
    yearSelect.appendChild(option);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const productSalesModal = document.getElementById("productSalesModal");

  // Modal açılırken satışları yükle ve yıl dropdown'ını doldur
  if (productSalesModal) {
    populateYearDropdown(); // Initial population
    productSalesModal.addEventListener("show.bs.modal", async (event) => {
      const button = event.relatedTarget;
      if (!button) return;

      currentProductSalesId = button.getAttribute("data-product-id");
      const code = button.getAttribute("data-product-code") || "";

      document.getElementById("productSalesProductCode").textContent = code;

      currentProductSalesEditIndex = null;

      // inputları temizle
      const priceInput = document.getElementById("productSalesSkuPrice");
      const qtyInput = document.getElementById("productSalesQuantity");
      const monthSelect = document.getElementById("productSalesMonth");

      if (priceInput) priceInput.value = "";
      if (qtyInput) qtyInput.value = "";
      // Ayı ve yılı mevcut tarihe ayarla
      const now = new Date();
      document.getElementById("productSalesYear").value = now.getFullYear();
      monthSelect.value = now.getMonth() + 1;


      try {
        const sales = await fetchSales(currentProductSalesId);
        renderProductSalesRows(sales);
      } catch (e) {
        renderProductSalesRows([]);
      }
    });
  }

  // Add record
  document.getElementById("addProductSalesBtn")?.addEventListener("click", async () => {
    const yearInput = document.getElementById("productSalesYear");
    const monthInput = document.getElementById("productSalesMonth");
    const qtyInput = document.getElementById("productSalesQuantity");
    const priceInput = document.getElementById("productSalesSkuPrice");

    const payload = {
      year: yearInput?.value,
      month: monthInput?.value,
      quantity: qtyInput?.value,
      sku_price: priceInput?.value || null, // Gönderilmemişse null yap
    };

    if (!payload.year || !payload.month || !payload.quantity) {
      alert("Please fill Year, Month and Quantity fields.");
      return;
    }

    const res = await fetch(`/add_product_sales/${currentProductSalesId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      alert("Error while saving sales data.");
      return;
    }

    const sales = await fetchSales(currentProductSalesId);
    renderProductSalesRows(sales);

    // Sadece quantity ve price'ı temizle
    qtyInput.value = "";
    priceInput.value = "";
  });

  // Edit/Save/Cancel/Delete actions (event delegation)
  document.getElementById("productSalesTableBody")?.addEventListener("click", async (e) => {
    const editBtn = e.target.closest(".product-sale-edit");
    const saveBtn = e.target.closest(".product-sale-save");
    const cancelBtn = e.target.closest(".product-sale-cancel");
    const deleteBtn = e.target.closest(".product-sale-delete");

    if (editBtn) {
      currentProductSalesEditIndex = parseInt(editBtn.getAttribute("data-index"), 10);
      renderProductSalesRows(currentProductSalesData);
      return;
    }

    if (cancelBtn) {
      currentProductSalesEditIndex = null;
      renderProductSalesRows(currentProductSalesData);
      return;
    }

    if (saveBtn) {
      const index = parseInt(saveBtn.getAttribute("data-index"), 10);
      const row = saveBtn.closest("tr");

      const payload = {
        year: row.querySelector(".edit-year")?.value,
        month: row.querySelector(".edit-month")?.value,
        quantity: row.querySelector(".edit-qty")?.value,
        sku_price: row.querySelector(".edit-sku")?.value || null,
      };

      const res = await fetch(`/update_product_sales/${currentProductSalesId}/${index}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        alert("Error updating sales record.");
        return;
      }

      const sales = await fetchSales(currentProductSalesId);
      currentProductSalesEditIndex = null;
      renderProductSalesRows(sales);
      return;
    }

    if (deleteBtn) {
      const index = deleteBtn.getAttribute("data-index");

      const res = await fetch(`/delete_product_sales/${currentProductSalesId}/${index}`, {
        method: "POST",
      });

      if (!res.ok) {
        alert("Error deleting sales record.");
        return;
      }

      const sales = await fetchSales(currentProductSalesId);
      currentProductSalesEditIndex = null;
      renderProductSalesRows(sales);
    }
  });
});
