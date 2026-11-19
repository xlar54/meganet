"""The permission registry: every permission key the server knows, with a short description.

A role (db.py) holds a set of these keys; session.can(key) asks whether the signed-on user's
role holds one. Features and game plugins register their own keys at import time:

    from meganet import permissions
    permissions.register("games.chess", "Play chess", like="games.play")

`like` says who gets a new key the first time the server sees it: every role that holds the
`like` key (so a new game is open to whoever could already play games). Roles with admin.roles
always get new keys too. After that, admins decide in the Roles window; the server never
re-grants a key an admin has taken away.

Descriptions are shown next to check boxes in the Roles window, so keep them to
DESCRIPTION_MAX characters or less (longer ones are cut).
"""

DESCRIPTION_MAX = 24

ADMIN_USERS = "admin.users"
ADMIN_ROLES = "admin.roles"
ADMIN_MOTD = "admin.motd"


class Permission:
    def __init__(self, key, description, like=None):
        self.key = key
        self.description = description
        self.like = like

    def __repr__(self):
        return "<Permission %s>" % self.key


_registry = {}          # key -> Permission, in registration order


def register(key, description, like=None):
    """Add a permission key (registering the same key again just updates its description).
    Returns the key, so a module can write  PLAY = permissions.register(...)."""
    if not key or " " in key:
        raise ValueError("bad permission key %r" % key)
    _registry[key] = Permission(key, description, like)
    return key


def all_permissions():
    """Every registered Permission, core ones first, then in registration order."""
    return list(_registry.values())


def get(key):
    return _registry.get(key)


def keys():
    return list(_registry)


def is_admin(key):
    return key.startswith("admin.")


# ---- the core permissions ----

CORE = [
    ("chat.use", "Chat in the lobby"),
    ("chat.moderate", "Moderate chat"),
    ("boards.read", "Read message boards"),
    ("boards.post", "Post on message boards"),
    ("boards.moderate", "Moderate boards"),
    ("news.read", "Read the news"),
    ("news.post", "Post, edit, delete news"),
    ("files.download", "Download files"),
    ("files.upload", "Upload files"),
    ("im.send", "Send instant messages"),
    ("games.play", "Play games"),
    ("gallery.view", "View the art gallery"),
    ("gallery.upload", "Upload art (IFF)"),
    ("music.listen", "Listen to SID music"),
    ("music.upload", "Upload SID music"),
    (ADMIN_USERS, "Admin: assign user roles"),
    (ADMIN_ROLES, "Admin: edit roles"),
    (ADMIN_MOTD, "Edit message of the day"),
]
for _key, _desc in CORE:
    register(_key, _desc)

# Added later: an existing database gives them out by the new-key rule (`like`).
ADMIN_PAGES = register("admin.pages", "Answer pages from users", like="chat.moderate")
MAIL_USE = register("mail.use", "Use private messages", like="chat.use")
CHAT_ROOMS = register("chat.rooms", "Make chat rooms", like="boards.post")
ADMIN_SETTINGS = register("admin.settings", "Admin: system settings")
ADMIN_BROADCAST = register("admin.broadcast", "Admin: broadcast")
POLLS_VOTE = register("polls.vote", "Vote in polls", like="chat.use")
POLLS_MANAGE = register("polls.manage", "Set up polls", like="boards.moderate")
FILES_MODERATE = register("files.moderate", "Manage file libraries", like="boards.moderate")
FILES_DOWNLOAD, FILES_UPLOAD = "files.download", "files.upload"
IM_SEND = "im.send"
NEWS_READ, NEWS_POST = "news.read", "news.post"     # (Sysop only at first: Roles gives it out)

# The roles a fresh database starts with: (name, level, permission keys). A higher level sorts
# lower in the lists. The last one gets every permission, admin ones included.
NEW_USER = ["chat.use", "games.play", "boards.read", "news.read", "gallery.view",
            "music.listen", MAIL_USE, POLLS_VOTE]
MEMBER = NEW_USER + ["boards.post", "files.download", "im.send", "gallery.upload",
                     CHAT_ROOMS]
MODERATOR = MEMBER + ["chat.moderate", "boards.moderate", ADMIN_PAGES, POLLS_MANAGE,
                      FILES_UPLOAD, FILES_MODERATE]
DEFAULT_ROLES = [
    ("New User", 10, NEW_USER),
    ("Member", 20, MEMBER),
    ("Moderator", 30, MODERATOR),
    ("Sysop", 100, None),            # None = everything registered (admin.motd included);
]                                    # older databases: admin roles get new keys at start-up
DEFAULT_ROLE = "New User"            # what new accounts get (an admin can change it)
FIRST_USER_ROLE = "Sysop"            # what the very first account gets
