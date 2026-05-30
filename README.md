# Blog Platform

A compact full-stack blogging platform with user authentication, CRUD blog posts, comments, RESTful APIs, and SQLite persistence.

## Run

```bash
python server.py
```

Open [http://localhost:8000](http://localhost:8000).

## Features

- Register, login, logout, and session-based authentication
- Create, edit, and delete your own posts
- Read all posts and open comment threads
- Add comments as a signed-in user
- SQLite database stored in `blog.db`

## API

- `POST /api/register`
- `POST /api/login`
- `POST /api/logout`
- `GET /api/me`
- `GET /api/posts`
- `POST /api/posts`
- `GET /api/posts/:id`
- `PUT /api/posts/:id`
- `DELETE /api/posts/:id`
- `POST /api/posts/:id/comments`
