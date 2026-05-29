const VaultWarden = (() => {
  const encoder = new TextEncoder();
  const decoder = new TextDecoder();
  const fallbackSalt = "helpdesk-pro-vaultwarden";
  const verifierPrefix = "helpdesk-pro-vault-verifier:";
  const config = window.VaultWardenConfig || {};
  let vaultProfile = config.profile || { configured: false };
  let setupSalt = config.setupSalt || null;
  const sessionStorageKey = "vaultwarden_passphrase";
  const typeIconMap = {
    login: "fa-solid fa-user-lock",
    secure_note: "fa-solid fa-note-sticky",
    card: "fa-solid fa-credit-card",
    identity: "fa-solid fa-id-card-clip",
    custom: "fa-solid fa-gears",
  };
  const typeLabelFallback = {
    login: "Login",
    secure_note: "Secure note",
    card: "Card",
    identity: "Identity",
    custom: "Custom item",
  };
  const customFieldSkipKeys = new Set([
    "name",
    "item_type",
    "tags",
    "folder",
    "notes",
    "username",
    "password",
    "uri",
    "secure_note",
    "cardholder",
    "card_number",
    "card_expiry",
    "card_cvc",
    "identity_name",
    "identity_email",
    "identity_phone",
    "identity_address",
  ]);
  let customFieldCounter = 0;
  let derivedKey = null;
  const collectionOrgMap = new Map();
  const orgKeyCache = new Map();
  const orgKeyPromises = new Map();

  const bufferToBase64 = (buffer) => btoa(String.fromCharCode(...new Uint8Array(buffer)));
  const base64ToBuffer = (value) => Uint8Array.from(atob(value), (c) => c.charCodeAt(0));

  const randomBase64 = (byteLength = 32) => {
    const bytes = crypto.getRandomValues(new Uint8Array(byteLength));
    return bufferToBase64(bytes);
  };

  const getActiveSalt = () => {
    if (vaultProfile?.configured && vaultProfile.kdf_salt) {
      return vaultProfile.kdf_salt;
    }
    if (!setupSalt) {
      setupSalt = randomBase64(16);
    }
    return setupSalt || fallbackSalt;
  };

  const deriveKey = async (passphrase, salt = getActiveSalt()) => {
    if (!passphrase) {
      derivedKey = null;
      return null;
    }
    if (window.argon2) {
      const result = await window.argon2.hash({
        pass: passphrase,
        salt,
        type: window.argon2.ArgonType.Argon2id,
        hashLen: 32,
        time: 2,
        mem: 1024,
      });
      const raw = Uint8Array.from(result.hash);
      return crypto.subtle.importKey("raw", raw, "AES-GCM", false, ["encrypt", "decrypt"]);
    }
    const baseKey = await crypto.subtle.importKey(
      "raw",
      encoder.encode(passphrase),
      { name: "PBKDF2" },
      false,
      ["deriveKey"],
    );
    return crypto.subtle.deriveKey(
      {
        name: "PBKDF2",
        salt: encoder.encode(salt),
        iterations: 200000,
        hash: "SHA-256",
      },
      baseKey,
      { name: "AES-GCM", length: 256 },
      false,
      ["encrypt", "decrypt"],
    );
  };

  const encryptPayload = async (payload, key) => {
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const data = encoder.encode(payload);
    const cipher = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, data);
    return {
      algorithm: "AES-GCM",
      version: 1,
      iv: bufferToBase64(iv),
      ciphertext: bufferToBase64(cipher),
    };
  };

  const decryptPayload = async (blob, key) => {
    if (!blob || !blob.ciphertext || !blob.iv) {
      throw new Error("Invalid blob");
    }
    const iv = base64ToBuffer(blob.iv);
    const ciphertext = base64ToBuffer(blob.ciphertext);
    const decrypted = await crypto.subtle.decrypt({ name: "AES-GCM", iv }, key, ciphertext);
    return decoder.decode(decrypted);
  };

  const updateKeyInfo = (passphrase) => {
    const hint = document.getElementById("vaultKeyHint");
    if (!hint) return;
    if (!passphrase) {
      hint.textContent = "";
      return;
    }
    hint.textContent = `Passphrase length: ${passphrase.length} chars`;
  };

  const updateUnlockStatus = (message = "", level = "muted") => {
    const status = document.getElementById("vaultUnlockStatus");
    if (!status) return;
    status.textContent = message;
    status.className = `small mt-1 text-${level}`;
  };

  const persistPassphraseForSession = (passphrase) => {
    if (!window.sessionStorage) return;
    const rememberCheckbox = document.getElementById("vaultRememberPassphrase");
    if (!rememberCheckbox || !rememberCheckbox.checked || !passphrase) {
      sessionStorage.removeItem(sessionStorageKey);
      return;
    }
    try {
      sessionStorage.setItem(sessionStorageKey, passphrase);
    } catch (err) {
      console.warn("Unable to persist vault passphrase:", err);
    }
  };

  const saveVaultProfile = async (kdfSalt, verificationBlob, accountPassword) => {
    const response = await fetch("/vaultwarden/profile", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-CSRFToken": config.csrfToken || "",
      },
      body: JSON.stringify({
        kdf_salt: kdfSalt,
        verification_blob: verificationBlob,
        account_password: accountPassword,
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || "Unable to save vault verification profile.");
    }
    vaultProfile = payload.profile || vaultProfile;
    return vaultProfile;
  };

  const getSetupCredentials = () => {
    if (vaultProfile?.configured) {
      return {};
    }
    const accountPassword = (document.getElementById("vaultAccountPassword")?.value || "").trim();
    const confirmation = (document.getElementById("vaultPassphraseConfirm")?.value || "").trim();
    if (!accountPassword) {
      throw new Error("Confirm your account password before setting up the vault.");
    }
    if (!confirmation) {
      throw new Error("Confirm the new vault passphrase.");
    }
    return { accountPassword, confirmation };
  };

  const unlockWithPassphrase = async (passphrase) => {
    const salt = getActiveSalt();
    const key = await deriveKey(passphrase, salt);
    if (!key) {
      throw new Error("Enter your vault passphrase.");
    }

    if (vaultProfile?.configured) {
      let decryptedVerifier = "";
      try {
        decryptedVerifier = await decryptPayload(vaultProfile.verification_blob, key);
      } catch (err) {
        throw new Error("Incorrect vault passphrase.");
      }
      if (!decryptedVerifier.startsWith(verifierPrefix)) {
        throw new Error("Incorrect vault passphrase.");
      }
      return key;
    }

    const { accountPassword, confirmation } = getSetupCredentials();
    if (passphrase !== confirmation) {
      throw new Error("Vault passphrases do not match.");
    }
    if (config.setupSampleBlob) {
      try {
        await decryptPayload(config.setupSampleBlob, key);
      } catch (err) {
        throw new Error("That passphrase cannot decrypt existing personal vault items.");
      }
    }
    const verificationBlob = await encryptPayload(`${verifierPrefix}${randomBase64(24)}`, key);
    await saveVaultProfile(salt, verificationBlob, accountPassword);
    return key;
  };

  const handlePassphraseInput = (event) => {
    const passphrase = event.target.value || "";
    updateKeyInfo(passphrase);
    updateUnlockStatus("");
    if (!passphrase) {
      persistPassphraseForSession("");
    }
  };

  const handlePassphrase = async (event, { notify = false } = {}) => {
    const passphrase = (event.target.value || "").trim();
    if (!passphrase) {
      derivedKey = null;
      updateKeyInfo("");
      updateUnlockStatus("");
      persistPassphraseForSession("");
      orgKeyCache.clear();
      orgKeyPromises.clear();
      if (notify) {
        showAlert("Vault passphrase cleared for this session.");
      }
      return false;
    }
    try {
      derivedKey = await unlockWithPassphrase(passphrase);
    } catch (err) {
      derivedKey = null;
      orgKeyCache.clear();
      orgKeyPromises.clear();
      updateUnlockStatus(err.message || "Unable to unlock the vault.", "danger");
      if (notify) {
        showAlert(err.message || "Unable to unlock the vault with that passphrase.");
      }
      return false;
    }
    updateKeyInfo(passphrase);
    persistPassphraseForSession(passphrase.trim());
    updateUnlockStatus("Vault unlocked for this session.", "success");
    loadOrganizationKeys();
    if (notify) {
      showAlert("Vault unlocked for this session.");
    }
    return true;
  };

  const setupPassphraseInput = () => {
    const input = document.getElementById("vaultPassphrase");
    if (!input) return;
    input.addEventListener("input", () => handlePassphraseInput({ target: input }));
    loadSessionPassphrase(input);
  };

  const promptForPassphraseIfNeeded = () => {
    if (derivedKey) {
      return;
    }
    if (window.sessionStorage && sessionStorage.getItem(sessionStorageKey)) {
      return;
    }
    const modalEl = document.getElementById("vaultEncryptionModal");
    if (!modalEl) {
      return;
    }
    const bootModal = new bootstrap.Modal(modalEl);
    bootModal.show();
  };
  const updateTypeSections = () => {
    const selector = document.getElementById("vaultItemType");
    if (!selector) return;
    const value = selector.value || "login";
    document.querySelectorAll(".vault-type-section").forEach((section) => {
      section.classList.toggle("d-none", section.dataset.type !== value);
    });
  };

  const setupTypeSwitcher = () => {
    const selector = document.getElementById("vaultItemType");
    if (!selector) return;
    selector.addEventListener("change", () => updateTypeSections());
    updateTypeSections();
  };
  const setupEncryptionActions = () => {
    document.getElementById("vaultClearPassphrase")?.addEventListener("click", (event) => {
      event.preventDefault();
      resetPassphrase();
    });
    const vaultPassphraseOk = document.getElementById("vaultPassphraseOk");
    if (vaultPassphraseOk) {
      vaultPassphraseOk.addEventListener("click", () => {
        const input = document.getElementById("vaultPassphrase");
        if (input) {
          handlePassphrase({ target: input }, { notify: true }).then((ok) => {
            if (ok) {
              const modalEl = document.getElementById("vaultEncryptionModal");
              if (modalEl) {
                bootstrap.Modal.getOrCreateInstance(modalEl).hide();
              }
            }
          });
        }
      });
    }
    setupRememberToggle();
  };

  const collectTypeFields = () => {
    const fields = {};
    document.querySelectorAll("[data-type-field]").forEach((element) => {
      fields[element.dataset.typeField] = element.value.trim();
    });
    return fields;
  };

  const setEncryptedField = async (form) => {
    const encryptedField = form.querySelector("input[name='encrypted_blob']");
    const metadataField = form.querySelector("input[name='metadata_blob']");
    const usernameField = document.getElementById("vaultItemUsername");
    const passwordField = document.getElementById("vaultItemPassword");
    const uriField = document.getElementById("vaultItemUri");
    const notesField = document.getElementById("vaultItemNotes");
    if (!encryptedField || !metadataField || !usernameField || !passwordField || !uriField || !notesField) {
      return
    }
    if (!derivedKey) {
      showAlert("Please unlock your vault by entering your passphrase before saving items.");
      return false;
    }
    const itemName = form.querySelector("input[name='name']").value.trim();
    const payload = {
      name: itemName,
      item_type: form.querySelector("select[name='item_type']").value,
      ...collectTypeFields(),
    };
    const metadata = {
      tags: form.querySelector("input[name='tags']").value.split(",").map((t) => t.trim()).filter(Boolean),
    };
    const collectionSelect = form.querySelector("select[name='collection_id']");
    const collectionId = collectionSelect ? parseInt(collectionSelect.value, 10) || 0 : 0;
    if (collectionId) {
      metadata.collection_id = collectionId;
      const orgId = collectionOrgMap.get(collectionId) || 0;
      if (orgId) {
        metadata.organization_id = orgId;
      }
    }
    let encryptionKey = null;
    try {
      encryptionKey = await getEncryptionKeyForCollection(collectionId);
    } catch (err) {
      showAlert(err.message || "Please unlock the vault to encrypt this item.");
      return false;
    }
    if (!encryptionKey) {
      showAlert("Missing encryption key for the selected collection.");
      return false;
    }
    const encrypted = await encryptPayload(JSON.stringify(payload), encryptionKey);
    encryptedField.value = JSON.stringify(encrypted);
    metadataField.value = JSON.stringify(metadata);
    return true;
  };

  const handleItemFormSubmit = (event) => {
    event.preventDefault();
    const form = event.target;
    setEncryptedField(form).then((ok) => {
      if (ok) {
        form.submit();
      }
    });
  };

  const setupItemForm = () => {
    const form = document.getElementById("vaultItemForm");
    if (!form) return;
    form.addEventListener("submit", handleItemFormSubmit);
  };

  const setupCollectionFilter = () => {
    const orgSelect = document.getElementById("vaultItemOrganization");
    const collectionSelect = document.getElementById("vaultItemCollection");
    if (!orgSelect || !collectionSelect) {
      return;
    }
    buildCollectionOrgMap();
    const options = Array.from(collectionSelect.querySelectorAll("option"));
    const updateCollections = () => {
      const selectedOrg = parseInt(orgSelect.value, 10) || 0;
      let hasVisibleSelection = false;
      options.forEach((option) => {
        const optionOrg = parseInt(option.dataset.org || "0", 10) || 0;
        const visible = selectedOrg === 0 || optionOrg === 0 || optionOrg === selectedOrg;
        option.hidden = !visible;
        if (visible && option.selected) {
          hasVisibleSelection = true;
        }
      });
      if (!hasVisibleSelection) {
        const firstVisible = options.find((option) => !option.hidden);
        if (firstVisible) {
          firstVisible.selected = true;
          collectionSelect.dispatchEvent(new Event("change", { bubbles: true }));
        }
      }
    };
    orgSelect.addEventListener("change", updateCollections);
    updateCollections();
  };

  const setupFolderFilter = () => {
    const folderSelect = document.getElementById("vaultItemFolder");
    const orgSelect = document.getElementById("vaultItemOrganization");
    const collectionSelect = document.getElementById("vaultItemCollection");
    if (!folderSelect) {
      return;
    }
    const options = Array.from(folderSelect.querySelectorAll("option"));
    const updateFolders = () => {
      const selectedOrg = parseInt(orgSelect?.value || "0", 10) || 0;
      const selectedCollection = parseInt(collectionSelect?.value || "0", 10) || 0;
      let hasVisibleSelection = false;
      options.forEach((option) => {
        const optionValue = parseInt(option.value, 10) || 0;
        const optionOrg = parseInt(option.dataset.org || "0", 10) || 0;
        const optionCollection = parseInt(option.dataset.collection || "0", 10) || 0;
        let visible = false;
        if (optionValue === 0) {
          visible = true;
        } else if (selectedCollection && optionCollection === selectedCollection) {
          visible = true;
        } else if (!selectedCollection && selectedOrg && optionOrg === selectedOrg) {
          visible = true;
        } else if (!selectedCollection && !selectedOrg && optionOrg === 0 && optionCollection === 0) {
          visible = true;
        }
        option.hidden = !visible;
        option.disabled = !visible;
        if (visible && option.selected) {
          hasVisibleSelection = true;
        }
      });
      if (!hasVisibleSelection) {
        const firstVisible = options.find((option) => !option.hidden);
        if (firstVisible) {
          firstVisible.selected = true;
        }
      }
    };
    [orgSelect, collectionSelect].forEach((select) => {
      select?.addEventListener("change", updateFolders);
    });
    updateFolders();
  };

  function showAlert(message) {
    const modal = document.getElementById("vaultAlertModal");
    if (!modal) {
      window.alert(message);
      return;
    }
    const output = modal.querySelector("#vaultAlertMessage");
    if (output) {
      output.textContent = message;
    }
    const bootModal = new bootstrap.Modal(modal);
    bootModal.show();
  }

  const resetPassphrase = () => {
    const input = document.getElementById("vaultPassphrase");
    if (input) {
      input.value = "";
    }
    derivedKey = null;
    updateKeyInfo("");
    updateUnlockStatus("");
    showAlert("Vault passphrase cleared for this session.");
    if (window.sessionStorage) {
      sessionStorage.removeItem(sessionStorageKey);
    }
    const remember = document.getElementById("vaultRememberPassphrase");
    if (remember) {
      remember.checked = false;
    }
  };

  function loadSessionPassphrase(input) {
    if (!window.sessionStorage || !input) {
      return;
    }
    if (vaultProfile?.reset_required) {
      sessionStorage.removeItem(sessionStorageKey);
      return;
    }
    const stored = sessionStorage.getItem(sessionStorageKey);
    if (!stored) {
      return;
    }
    input.value = stored;
    const remember = document.getElementById("vaultRememberPassphrase");
    if (remember) {
      remember.checked = true;
    }
    handlePassphrase({ target: input });
  };

  function setupRememberToggle() {
    const checkbox = document.getElementById("vaultRememberPassphrase");
    if (!checkbox) return;
    checkbox.addEventListener("change", () => {
      if (!checkbox.checked && window.sessionStorage) {
        sessionStorage.removeItem(sessionStorageKey);
      }
      const input = document.getElementById("vaultPassphrase");
      if (checkbox.checked && input) {
        persistPassphraseForSession(input.value.trim());
      }
    });
  };

  const buildCollectionOrgMap = () => {
    const options = document.querySelectorAll("#vaultItemCollection option");
    if (!options.length) return;
    collectionOrgMap.clear();
    options.forEach((option) => {
      const collectionId = parseInt(option.value, 10) || 0;
      const orgId = parseInt(option.dataset.org || "0", 10) || 0;
      if (collectionId > 0) {
        collectionOrgMap.set(collectionId, orgId);
      }
    });
  };

  const fetchOrganizationKey = async (orgId) => {
    if (!orgId) {
      return null;
    }
    if (orgKeyCache.has(orgId)) {
      return orgKeyCache.get(orgId);
    }
    if (orgKeyPromises.has(orgId)) {
      return orgKeyPromises.get(orgId);
    }
    const promise = fetch(`/vaultwarden/organizations/${orgId}/key`, {
      credentials: "same-origin",
      headers: {
        "Accept": "application/json",
      },
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error("Unable to retrieve organization key.");
        }
        return response.json();
      })
      .then((payload) => {
        if (!payload || !payload.key_blob) {
          throw new Error("Organization key is not available.");
        }
        const raw = base64ToBuffer(payload.key_blob);
        return crypto.subtle.importKey(
          "raw",
          raw,
          { name: "AES-GCM" },
          false,
          ["encrypt", "decrypt"],
        );
      })
      .then((key) => {
        orgKeyCache.set(orgId, key);
        orgKeyPromises.delete(orgId);
        return key;
      })
      .catch((error) => {
        orgKeyPromises.delete(orgId);
        showAlert(error.message || "Unable to load organization key.");
        throw error;
      });
    orgKeyPromises.set(orgId, promise);
    return promise;
  };

  const loadOrganizationKeys = () => {
    const orgIds = Array.isArray(window.VaultWardenSharedOrganizations)
      ? window.VaultWardenSharedOrganizations
      : [];
    if (!orgIds.length) {
      return;
    }
    orgIds.forEach((orgId) => {
      if (!orgId) {
        return;
      }
      fetchOrganizationKey(orgId).catch(() => {});
    });
  };

  const getEncryptionKeyForCollection = async (collectionId) => {
    const orgId = collectionOrgMap.get(collectionId);
    if (orgId) {
      const orgKey = await fetchOrganizationKey(orgId);
      if (orgKey) {
        return orgKey;
      }
    }
    if (!derivedKey) {
      throw new Error("Vault is locked. Unlock it to encrypt items.");
    }
    return derivedKey;
  };

  const resetToggleButton = (targetId) => {
    const button = document.querySelector(`[data-vault-toggle-target="${targetId}"]`);
    if (!button) return;
    button.dataset.vaultToggleState = "hidden";
    button.innerHTML = '<i class="fa-solid fa-eye"></i>';
  };

  const setDetailFieldValue = (id, value, { mask = false } = {}) => {
    const element = document.getElementById(id);
    if (!element) return;
    const normalized = value == null ? "" : String(value);
    element.dataset.vaultRaw = normalized;
    if (mask) {
      const maskValue = normalized ? "•".repeat(Math.max(8, normalized.length)) : "-";
      element.dataset.vaultMasked = maskValue;
      element.textContent = maskValue || "-";
      resetToggleButton(id);
    } else {
      element.textContent = normalized || "-";
    }
  };

  const setTextContent = (id, value, fallback = "-") => {
    const element = document.getElementById(id);
    if (element) {
      element.textContent = value || fallback;
    }
  };

  const toggleFieldVisibility = (button) => {
    const targetId = button.dataset.vaultToggleTarget;
    const element = document.getElementById(targetId);
    if (!element) return;
    const rawValue = element.dataset.vaultRaw || "";
    const maskedValue = element.dataset.vaultMasked || rawValue.replace(/./g, "•");
    const isVisible = button.dataset.vaultToggleState === "visible";
    if (isVisible) {
      element.textContent = maskedValue || "-";
      button.dataset.vaultToggleState = "hidden";
      button.innerHTML = '<i class="fa-solid fa-eye"></i>';
    } else {
      element.textContent = rawValue || "-";
      button.dataset.vaultToggleState = "visible";
      button.innerHTML = '<i class="fa-solid fa-eye-slash"></i>';
    }
  };

  const handleToggleClick = (event) => {
    const button = event.target.closest("[data-vault-toggle-target]");
    if (!button) return;
    event.preventDefault();
    toggleFieldVisibility(button);
  };

  const setupToggleButtons = () => {
    document.body.addEventListener("click", handleToggleClick);
  };

  const updateDetailSections = (type) => {
    document.querySelectorAll(".vault-detail-section").forEach((section) => {
      section.classList.toggle("d-none", section.dataset.type !== type);
    });
  };

  const updateTypeBadge = (type, label) => {
    const icon = document.getElementById("vaultDetailTypeIcon");
    if (icon) {
      const iconClass = typeIconMap[type] || "fa-solid fa-shield-alt";
      icon.className = `${iconClass} me-1`;
    }
    const text = document.getElementById("vaultDetailTypeText");
    if (text) {
      text.textContent = label || typeLabelFallback[type] || type || "-";
    }
  };

  const updateCollectionText = (value) => {
    const element = document.getElementById("vaultDetailCollectionText");
    if (!element) return;
    const fallback = element.dataset.defaultText || "-";
    element.textContent = value || fallback;
  };

  const populateCustomFields = (payload) => {
    const container = document.getElementById("vaultDetailCustomFields");
    const placeholder = document.getElementById("vaultDetailCustomPlaceholder");
    if (!container) return;
    container.innerHTML = "";
    const entries = Object.entries(payload ?? {}).filter(
      ([key, value]) =>
        !customFieldSkipKeys.has(key) &&
        value !== undefined &&
        value !== null &&
        value !== "",
    );
    if (!entries.length) {
      if (placeholder) {
        placeholder.classList.remove("d-none");
      }
      return;
    }
    if (placeholder) {
      placeholder.classList.add("d-none");
    }
    const copyTitle = container.dataset.copyTitle || "Copy value";
    entries.forEach(([key, value]) => {
      const label = key.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
      const fieldId = `vaultDetailCustomField-${key}-${++customFieldCounter}`;
      const field = document.createElement("div");
      field.className = "vault-detail-field mb-2";
      const header = document.createElement("div");
      header.className = "d-flex justify-content-between align-items-center";
      const labelEl = document.createElement("span");
      labelEl.className = "vault-detail-field-label small text-uppercase text-muted";
      labelEl.innerHTML = `<i class="fa-solid fa-hashtag me-1"></i>${label}`;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "btn btn-outline-secondary btn-sm";
      button.dataset.copyTarget = fieldId;
      button.title = copyTitle;
      button.innerHTML = '<i class="fa-solid fa-copy"></i>';
      header.append(labelEl, button);
      const valueEl = document.createElement("p");
      valueEl.id = fieldId;
      valueEl.className = "vault-detail-value mb-0";
      valueEl.textContent = value == null ? "-" : String(value);
      field.append(header, valueEl);
      container.appendChild(field);
    });
  };

  const clearCustomFields = () => {
    const container = document.getElementById("vaultDetailCustomFields");
    if (container) {
      container.innerHTML = "";
    }
    const placeholder = document.getElementById("vaultDetailCustomPlaceholder");
    if (placeholder) {
      placeholder.classList.add("d-none");
    }
  };

  const showDetailModal = async (event) => {
    const target = event.currentTarget;
    const rawBlob = target.dataset.vaultBlob;
    if (!rawBlob) return;
    const blob = JSON.parse(rawBlob);
    if (!derivedKey) {
      showAlert("Unlock the vault before decrypting item details.");
      return;
    }
    try {
      const collectionId = parseInt(target.dataset.vaultCollectionId || "0", 10) || 0;
      const encryptionKey = await getEncryptionKeyForCollection(collectionId);
      const decrypted = await decryptPayload(blob, encryptionKey);
      let payload = null;
      try {
        payload = JSON.parse(decrypted);
      } catch (err) {
        payload = null;
      }
      const requestedType = (payload?.item_type || target.dataset.vaultType || "login").toLowerCase();
      const type = typeIconMap[requestedType] ? requestedType : "login";
      const typeLabel = target.dataset.vaultTypeLabel || typeLabelFallback[type] || type;
      const folderLabel = target.dataset.vaultFolder || payload?.folder;
      setDetailFieldValue("vaultDetailUsername", payload?.username);
      setDetailFieldValue("vaultDetailPassword", payload?.password, { mask: true });
      setDetailFieldValue("vaultDetailUri", payload?.uri);
      setDetailFieldValue("vaultDetailNotes", payload?.notes);
      setDetailFieldValue("vaultDetailSecureNote", payload?.secure_note || payload?.notes);
      setDetailFieldValue("vaultDetailCardholder", payload?.cardholder);
      setDetailFieldValue("vaultDetailCardNumber", payload?.card_number, { mask: true });
      setDetailFieldValue("vaultDetailCardExpiry", payload?.card_expiry);
      setDetailFieldValue("vaultDetailCardCvc", payload?.card_cvc, { mask: true });
      setDetailFieldValue("vaultDetailIdentityName", payload?.identity_name);
      setDetailFieldValue("vaultDetailIdentityEmail", payload?.identity_email);
      setDetailFieldValue("vaultDetailIdentityPhone", payload?.identity_phone);
      setDetailFieldValue("vaultDetailIdentityAddress", payload?.identity_address);
      updateDetailSections(type);
      updateTypeBadge(type, typeLabel);
      updateCollectionText(folderLabel);
      if (type === "custom") {
        populateCustomFields(payload ?? {});
      } else {
        clearCustomFields();
      }
      const status = document.getElementById("vaultDetailStatus");
      if (status) {
        const unlocked = status.dataset.decryptedText || "Unlocked";
        status.innerHTML = `<i class=\"fa-solid fa-unlock me-1\"></i>${unlocked}`;
      }
      setTextContent("vaultDetailName", target.dataset.vaultLabel || payload?.name || decrypted);
      const rawOutput = document.getElementById("vaultDetailRaw");
      if (rawOutput) {
        rawOutput.textContent = decrypted;
        rawOutput.hidden = Boolean(payload);
      }
      const modal = document.getElementById("vaultDetailModal");
      const bootstrapModal = new bootstrap.Modal(modal);
      bootstrapModal.show();
    } catch (err) {
      console.error(err);
      showAlert("Unable to decrypt this item. Please ensure your passphrase is correct.");
    }
  };

  const setupDetailButtons = () => {
    document.querySelectorAll("[data-vault-blob]").forEach((button) => {
      button.addEventListener("click", showDetailModal);
    });
  };

  const copyFieldValue = async (button) => {
    try {
      const target = button.dataset.copyTarget;
      if (!target) return;
      const element = document.getElementById(target);
      if (!element) return;
      const text = element.textContent || element.value || "";
      await navigator.clipboard.writeText(text.trim());
      button.classList.add("btn-success");
      setTimeout(() => button.classList.remove("btn-success"), 800);
    } catch (err) {
      console.error(err);
    }
  };

  const handleClipboardClick = async (event) => {
    const button = event.target.closest("[data-copy-target]");
    if (!button) return;
    event.preventDefault();
    await copyFieldValue(button);
  };

  const setupClipboardButtons = () => {
    document.body.addEventListener("click", handleClipboardClick);
  };

  const scorePassword = (value) => {
    let score = 0;
    const sets = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/];
    if (value.length >= 8) score += 1;
    if (value.length >= 12) score += 1;
    sets.forEach((re) => {
      if (re.test(value)) score += 1;
    });
    return Math.min(score, 5);
  };

  const updateStrengthMeter = (value) => {
    const meter = document.getElementById("vaultStrengthMeter");
    if (!meter) return;
    const progress = document.getElementById("vaultStrengthProgress");
    const score = scorePassword(value);
    const percent = (score / 5) * 100;
    meter.style.width = `${percent}%`;
    if (score <= 2) {
      meter.classList.remove("bg-success", "bg-warning");
      meter.classList.add("bg-danger");
    } else if (score <= 3) {
      meter.classList.remove("bg-danger", "bg-success");
      meter.classList.add("bg-warning");
    } else {
      meter.classList.remove("bg-danger", "bg-warning");
      meter.classList.add("bg-success");
    }
    if (progress) {
      progress.textContent = [`Weak`, `Fair`, `Fair`, `Strong`, `Strong`, `Very strong`][score];
    }
  };

  const generatePassword = () => {
    const lengthEl = document.getElementById("vaultGeneratorLength");
    const includeUpperEl = document.getElementById("vaultIncludeUpper");
    const includeLowerEl = document.getElementById("vaultIncludeLower");
    const includeNumbersEl = document.getElementById("vaultIncludeNumbers");
    const includeSymbolsEl = document.getElementById("vaultIncludeSymbols");
    if (!lengthEl || !includeUpperEl || !includeLowerEl || !includeNumbersEl || !includeSymbolsEl) {
      return;
    }
    const length = parseInt(lengthEl.value, 10) || 16;
    const includeUpper = includeUpperEl.checked;
    const includeLower = includeLowerEl.checked;
    const includeNumbers = includeNumbersEl.checked;
    const includeSymbols = includeSymbolsEl.checked;
    const pools = [];
    if (includeLower) pools.push("abcdefghijklmnopqrstuvwxyz");
    if (includeUpper) pools.push("ABCDEFGHIJKLMNOPQRSTUVWXYZ");
    if (includeNumbers) pools.push("0123456789");
    if (includeSymbols) pools.push("!@#$%&*()-_=+[]{};:,<>.?/");
    if (!pools.length) {
      pools.push("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789");
    }
    const chars = [];
    for (let i = 0; i < length; i++) {
      const pool = pools[i % pools.length];
      const idx = crypto.getRandomValues(new Uint32Array(1))[0] % pool.length;
      chars.push(pool[idx]);
    }
    const result = chars.join("");
    const output = document.getElementById("vaultGeneratorOutput");
    if (output) {
      output.value = result;
      updateStrengthMeter(result);
    }
  };

  const setupGenerator = () => {
    const lengthInput = document.getElementById("vaultGeneratorLength");
    if (lengthInput) {
      lengthInput.addEventListener("input", () => generatePassword());
    }
    ["vaultIncludeUpper", "vaultIncludeLower", "vaultIncludeNumbers", "vaultIncludeSymbols"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) {
        el.addEventListener("change", () => generatePassword());
      }
    });
    const button = document.getElementById("vaultGeneratorButton");
    if (button) {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        generatePassword();
      });
    }
    const output = document.getElementById("vaultGeneratorOutput");
    if (output) {
      output.addEventListener("input", (event) => {
        updateStrengthMeter(event.target.value);
      });
    }
    generatePassword();
  };

  const init = () => {
    setupPassphraseInput();
    promptForPassphraseIfNeeded();
    setupEncryptionActions();
    setupItemForm();
    setupTypeSwitcher();
    setupFolderFilter();
    setupCollectionFilter();
    setupDetailButtons();
    setupToggleButtons();
    setupClipboardButtons();
    setupGenerator();
  };

  return {
    init,
    decryptPayload,
  };
})();

document.addEventListener("DOMContentLoaded", () => {
  VaultWarden.init();
});
