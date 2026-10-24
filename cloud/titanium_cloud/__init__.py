"""The cloud API of laboratories (feature electron, DEC-058): a FastAPI application on Vercel over one Neon database, with Neon Auth as
the sign-in. It keeps public and invitation-only laboratories, their immutable releases as 1 MiB chunks, invitations, memberships and
withdrawals; every release is validated with the same reader (``_lab_format``) the desktop uses."""
__version__ = "0.1.0"
