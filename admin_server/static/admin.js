// admin.js – script da UI de administração

let adminToken = localStorage.getItem("ro_admin_token") || "";

// Elementos da UI
const tokenInput = document.getElementById("adminTokenInput");
const authBtn = document.getElementById("authBtn");
const authStatus = document.getElementById("authStatus");
const keyForm = document.getElementById("keyForm");
const keyTableBody = document.querySelector("#keyTable tbody");
const refreshBtn = document.getElementById("refreshBtn");
const copyBtn = document.getElementById("copyBtn");

// Inicialização
if (adminToken) {
  tokenInput.value = adminToken;
  updateAuthStatus(true);
  loadKeys();
}

// Atualiza o estado visual de autenticação
function updateAuthStatus(isConnected) {
  if (isConnected) {
    authStatus.textContent = "Conectado";
    authStatus.className = "status-indicator connected";
    authBtn.textContent = "Sair";
  } else {
    authStatus.textContent = "Desconectado";
    authStatus.className = "status-indicator";
    authBtn.textContent = "Entrar";
  }
}

// Manipulador de clique no botão de autenticar
authBtn.addEventListener("click", () => {
  if (adminToken) {
    // Ação de Logout
    adminToken = "";
    localStorage.removeItem("ro_admin_token");
    tokenInput.value = "";
    updateAuthStatus(false);
    keyTableBody.innerHTML = `<tr><td colspan="7" class="empty-state">Insira o Admin Token para carregar as licenças.</td></tr>`;
  } else {
    // Ação de Login
    const inputVal = tokenInput.value.trim();
    if (inputVal) {
      adminToken = inputVal;
      localStorage.setItem("ro_admin_token", adminToken);
      updateAuthStatus(true);
      loadKeys();
    }
  }
});

// Atualiza a tabela sempre que pressionar Enter no input
tokenInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    const inputVal = tokenInput.value.trim();
    if (inputVal) {
      adminToken = inputVal;
      localStorage.setItem("ro_admin_token", adminToken);
      updateAuthStatus(true);
      loadKeys();
    }
  }
});

/**
 * Busca todas as chaves armazenadas e preenche a tabela com botões de ação.
 */
async function loadKeys() {
  if (!adminToken) return;
  
  try {
    const resp = await fetch("/admin/keys", {
      headers: { "X-Admin-Token": adminToken }
    });
    
    if (resp.status === 403) {
      updateAuthStatus(false);
      authStatus.textContent = "Token Inválido";
      authStatus.className = "status-indicator error";
      keyTableBody.innerHTML = `<tr><td colspan="7" class="empty-state" style="color: #f87171;">O Token fornecido é inválido. Tente novamente.</td></tr>`;
      return;
    }
    
    if (!resp.ok) {
      throw new Error("Erro na rede ou servidor.");
    }

    const keys = await resp.json();
    
    // Atualiza estado de conectado se deu tudo certo
    updateAuthStatus(true);
    
    if (keys.length === 0) {
      keyTableBody.innerHTML = `<tr><td colspan="7" class="empty-state">Nenhuma chave cadastrada no sistema.</td></tr>`;
      return;
    }

    keyTableBody.innerHTML = "";
    keys.forEach(k => {
      const tr = document.createElement("tr");
      
      const createdDate = k.createdAt ? new Date(k.createdAt).toLocaleDateString("pt-BR") : "-";
      const statusBadge = k.isActive 
        ? `<span class="badge active">Ativa</span>` 
        : `<span class="badge inactive">Inativa</span>`;
        
      const machineId = k.activatedMachineId 
        ? `<span title="${k.activatedMachineId}">${k.activatedMachineId.substring(0, 12)}...</span>` 
        : '<span style="color: var(--text-secondary); font-style: italic;">Não ativado</span>';

      tr.innerHTML = `
        <td><code>${k.productKey}</code></td>
        <td><strong style="text-transform: capitalize;">${k.tier}</strong></td>
        <td>${k.durationDays} dias</td>
        <td>${statusBadge}</td>
        <td>${machineId}</td>
        <td>${createdDate}</td>
        <td>
          <div class="action-btn-group">
            <button class="btn secondary-btn tbl-btn toggle" data-key="${k.productKey}" data-active="${k.isActive}">
              ${k.isActive ? "Desativar" : "Ativar"}
            </button>
            <button class="btn primary-btn tbl-btn delete" data-key="${k.productKey}">
              Excluir
            </button>
          </div>
        </td>`;
      keyTableBody.appendChild(tr);
    });
  } catch (e) {
    console.error("Erro ao carregar chaves", e);
    keyTableBody.innerHTML = `<tr><td colspan="7" class="empty-state" style="color: #f87171;">Falha de conexão com o servidor.</td></tr>`;
  }
}

/**
 * Exclui uma chave pelo token admin.
 */
async function deleteKey(productKey) {
  if (!confirm(`Tem certeza de que deseja excluir permanentemente a chave ${productKey}?`)) {
    return;
  }
  
  try {
    const resp = await fetch(`/admin/keys/${encodeURIComponent(productKey)}`, {
      method: "DELETE",
      headers: { "X-Admin-Token": adminToken }
    });
    
    if (resp.ok) {
      loadKeys();
    } else {
      alert("Erro ao excluir chave de produto.");
    }
  } catch (e) {
    console.error(e);
  }
}

/**
 * Alterna o status ativo de uma chave.
 */
async function toggleKey(productKey, currentlyActive) {
  try {
    const resp = await fetch(`/admin/keys/${encodeURIComponent(productKey)}/activate`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "X-Admin-Token": adminToken
      },
      body: JSON.stringify({ is_active: !currentlyActive })
    });
    
    if (resp.ok) {
      loadKeys();
    } else {
      alert("Erro ao alterar status da chave.");
    }
  } catch (e) {
    console.error(e);
  }
}

// Delegação de eventos para botões de ação na tabela
keyTableBody.addEventListener("click", e => {
  const target = e.target;
  if (target.classList.contains("delete")) {
    const key = target.dataset.key;
    deleteKey(key);
  } else if (target.classList.contains("toggle")) {
    const key = target.dataset.key;
    const isActive = target.dataset.active === "true";
    toggleKey(key, isActive);
  }
});

/**
 * Envia requisição para gerar nova chave de licença.
 */
async function generateKey(event) {
  event.preventDefault();
  if (!adminToken) {
    alert("Insira o Admin Token antes de tentar gerar uma licença.");
    return;
  }
  
  const tier = document.getElementById("tier").value;
  const duration = Number(document.getElementById("duration").value);
  const isActive = document.getElementById("active").checked;

  const payload = {
    tier,
    duration_days: duration,
    is_active: isActive,
  };

  try {
    const resp = await fetch("/admin/generate-key", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Admin-Token": adminToken,
      },
      body: JSON.stringify(payload),
    });
    
    const data = await resp.json();
    const resultDiv = document.getElementById("result");
    
    if (data.success && data.productKey) {
      document.getElementById("generatedKey").textContent = data.productKey;
      resultDiv.classList.remove("hidden");
      loadKeys();
    } else {
      alert(data.detail || "Erro ao gerar chave de produto.");
    }
  } catch (err) {
    console.error("Erro na requisição", err);
    alert("Falha de rede ao tentar gerar chave.");
  }
}

/**
 * Copia a chave gerada para a área de transferência.
 */
function copyKey() {
  const key = document.getElementById("generatedKey").textContent;
  if (!key) return;
  navigator.clipboard.writeText(key).then(() => {
    const originalText = copyBtn.textContent;
    copyBtn.textContent = "Copiado!";
    setTimeout(() => {
      copyBtn.textContent = originalText;
    }, 2000);
  }).catch(err => {
    console.error("Não foi possível copiar", err);
  });
}

// Registrar Eventos
keyForm.addEventListener("submit", generateKey);
refreshBtn.addEventListener("click", loadKeys);
copyBtn.addEventListener("click", copyKey);
