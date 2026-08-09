# Server

This directory will contain the OpenQSP server project and its supporting documentation and tests.

## M6 accounts and authenticated TCP

Initialize/provision and run a node:

```console
openqsp-server --database openqsp.db --create-account EA3AAA 'choose-a-password'
openqsp-server --database openqsp.db
openqsp-client --callsign EA3AAA
```

Provisioning is local administration, not public registration. Passwords are salted PBKDF2-HMAC-SHA256 values. Production TCP accepts only bounded `AUTH` exchanges; the old callsign-only path is an explicit automated-test compatibility option.
