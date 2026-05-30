const state = {
  user: null,
  authMode: "login",
  editingPost: null,
};

const sessionEl = document.querySelector("#session");
const authPanel = document.querySelector("#authPanel");
const editorPanel = document.querySelector("#editorPanel");
const authForm = document.querySelector("#authForm");
const authSubmit = document.querySelector("#authSubmit");
const postForm = document.querySelector("#postForm");
const postTitle = document.querySelector("#postTitle");
const postContent = document.querySelector("#postContent");
const editorTitle = document.querySelector("#editorTitle");
const cancelEdit = document.querySelector("#cancelEdit");
const postsEl = document.querySelector("#posts");
const statusEl = document.querySelector("#status");
const template = document.querySelector("#postTemplate");

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Request failed");
  }
  return payload;
}

function setStatus(message) {
  statusEl.textContent = message;
  if (message) {
    setTimeout(() => {
      if (statusEl.textContent === message) statusEl.textContent = "";
    }, 3500);
  }
}

function formatDate(value) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function updateSession() {
  authPanel.classList.toggle("hidden", Boolean(state.user));
  editorPanel.classList.toggle("hidden", !state.user);
  if (!state.user) {
    sessionEl.replaceChildren(document.createTextNode("Guest"));
    return;
  }
  const label = document.createElement("span");
  label.textContent = `Signed in as ${state.user.username}`;
  const logoutButton = document.createElement("button");
  logoutButton.className = "secondary";
  logoutButton.textContent = "Logout";
  sessionEl.replaceChildren(label, logoutButton);
  logoutButton.addEventListener("click", async () => {
    await api("/api/logout", { method: "POST" });
    state.user = null;
    resetEditor();
    updateSession();
    await loadPosts();
  });
}

function resetEditor() {
  state.editingPost = null;
  editorTitle.textContent = "Create post";
  postForm.reset();
  cancelEdit.classList.add("hidden");
}

async function loadMe() {
  const payload = await api("/api/me");
  state.user = payload.user;
  updateSession();
}

async function loadPosts() {
  const posts = await api("/api/posts");
  postsEl.innerHTML = "";
  if (posts.length === 0) {
    postsEl.innerHTML = '<p class="meta">No posts yet. Sign in and publish the first one.</p>';
    return;
  }
  posts.forEach(renderPost);
}

function renderPost(post) {
  const node = template.content.cloneNode(true);
  const article = node.querySelector(".post");
  article.querySelector("h3").textContent = post.title;
  article.querySelector(".meta").textContent = `By ${post.author} - ${formatDate(post.created_at)}`;
  article.querySelector(".content").textContent = post.content;
  const toggle = article.querySelector(".comments-toggle");
  toggle.textContent = `${post.comment_count} comment${post.comment_count === 1 ? "" : "s"}`;

  const ownerActions = article.querySelector(".owner-actions");
  if (state.user && state.user.id === post.author_id) {
    ownerActions.classList.remove("hidden");
    article.querySelector(".edit").addEventListener("click", () => startEdit(post));
    article.querySelector(".delete").addEventListener("click", () => deletePost(post.id));
  }

  toggle.addEventListener("click", () => openComments(article, post.id));
  article.querySelector(".comment-form").addEventListener("submit", (event) => submitComment(event, post.id, article));
  postsEl.appendChild(node);
}

async function renderComments(article, postId) {
  const listEl = article.querySelector(".comment-list");
  const post = await api(`/api/posts/${postId}`);
  listEl.innerHTML = "";
  if (post.comments.length === 0) {
    const empty = document.createElement("p");
    empty.className = "meta";
    empty.textContent = "No comments yet.";
    listEl.appendChild(empty);
  } else {
    post.comments.forEach((comment) => {
      const item = document.createElement("div");
      const author = document.createElement("strong");
      const body = document.createElement("span");
      item.className = "comment";
      author.textContent = comment.author;
      body.textContent = comment.body;
      item.append(author, body);
      listEl.appendChild(item);
    });
  }
  article.querySelector(".comment-form").classList.toggle("hidden", !state.user);
}

async function openComments(article, postId) {
  const commentsEl = article.querySelector(".comments");
  commentsEl.classList.toggle("hidden");
  if (commentsEl.classList.contains("hidden")) return;
  await renderComments(article, postId);
}

function startEdit(post) {
  state.editingPost = post.id;
  editorTitle.textContent = "Edit post";
  postTitle.value = post.title;
  postContent.value = post.content;
  cancelEdit.classList.remove("hidden");
  postTitle.focus();
}

async function deletePost(postId) {
  if (!confirm("Delete this post?")) return;
  await api(`/api/posts/${postId}`, { method: "DELETE" });
  setStatus("Post deleted");
  await loadPosts();
}

async function submitComment(event, postId, article) {
  event.preventDefault();
  const input = event.currentTarget.querySelector("input");
  await api(`/api/posts/${postId}/comments`, {
    method: "POST",
    body: JSON.stringify({ body: input.value }),
  });
  input.value = "";
  setStatus("Comment added");
  article.querySelector(".comments").classList.remove("hidden");
  await renderComments(article, postId);
  await loadPosts();
}

document.querySelectorAll("[data-auth-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    state.authMode = button.dataset.authTab;
    document.querySelectorAll("[data-auth-tab]").forEach((tab) => tab.classList.toggle("active", tab === button));
    authSubmit.textContent = state.authMode === "login" ? "Login" : "Create account";
  });
});

authForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    username: document.querySelector("#username").value,
    password: document.querySelector("#password").value,
  };
  try {
    const result = await api(`/api/${state.authMode}`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.user = result.user;
    authForm.reset();
    updateSession();
    await loadPosts();
  } catch (error) {
    setStatus(error.message);
  }
});

postForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    title: postTitle.value,
    content: postContent.value,
  };
  const path = state.editingPost ? `/api/posts/${state.editingPost}` : "/api/posts";
  const method = state.editingPost ? "PUT" : "POST";
  try {
    await api(path, { method, body: JSON.stringify(payload) });
    setStatus(state.editingPost ? "Post updated" : "Post published");
    resetEditor();
    await loadPosts();
  } catch (error) {
    setStatus(error.message);
  }
});

cancelEdit.addEventListener("click", resetEditor);

loadMe()
  .then(loadPosts)
  .catch((error) => setStatus(error.message));
