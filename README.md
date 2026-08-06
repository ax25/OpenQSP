# OpenQSP

> A modern, transport-independent messaging platform for amateur radio.

OpenQSP is an open-source communication platform designed for amateur radio operators. It provides persistent messaging over multiple transports while exposing a single, modern application protocol.

Unlike traditional APRS messaging, OpenQSP is **not tied to any specific transport**. APRS is simply one of the supported communication media.

The same architecture is designed to operate over:

- Internet
- APRS
- AX.25 Packet
- LoRa
- VARA FM
- VARA HF
- Future transports

The objective is to provide reliable, store-and-forward communications over slow and intermittent links without changing the user experience.

---

# Vision

Modern messaging applications assume permanent Internet connectivity.

OpenQSP starts from the opposite assumption:

> Internet may not exist, but radio still does.

The project aims to offer a consistent messaging experience regardless of the transport being used.

Whether a user connects through APRS, Packet, LoRa or the Internet, they always interact with the same mailbox, the same conversations and the same identity.

---

# Core Principles

- Transport-independent application protocol.
- Persistent store-and-forward messaging.
- Optimized for extremely low-bandwidth links.
- Designed for intermittent connectivity.
- One identity (callsign) across every transport.
- Open protocol.
- Extensible architecture.
- Open-source community project.

---

# Features

## Persistent Messaging

Messages remain stored until the recipient receives them.

Delivery does not depend on both users being online simultaneously.

## Low-Speed Chat

Conversations optimized for slow radio links.

Reliable delivery using acknowledgements and retries.

## Internal Mail

Permanent mailbox including:

- Inbox
- Sent
- Drafts

## News & Bulletins

Topic-based channels that can be downloaded on demand.

Examples:

- General news
- Weather
- Amateur radio activity
- Clubs
- Events
- Emergency bulletins

## Multiple Transports

The application protocol is independent from the underlying transport.

Current and planned transports include:

- Internet
- APRS
- AX.25 Packet
- LoRa
- VARA FM
- VARA HF

Future transports can be added without changing the application layer.

---

# Architecture

```
                     +----------------------+
                     |      OpenQSP         |
                     |    Application Core  |
                     +----------+-----------+
                                |
                Transport-independent protocol
                                |
          +---------+-----------+-----------+----------+
          |         |           |           |          |
      Internet     APRS      AX.25      LoRa      VARA
```

Every transport implements the same application protocol.

The server decides how messages are delivered according to transport availability and user preferences.

---

# Repository Structure

```
OpenQSP/
│
├── app/          Flutter client
├── server/       OpenQSP server
├── protocol/     Protocol specification
├── design/       Architecture and design decisions
├── docs/         Documentation
├── examples/     Example implementations
└── tools/        Development tools
```

---

# Current Status

🚧 **Early Design Phase**

The project is currently focused on defining:

- Overall architecture
- Application protocol
- Transport abstraction
- APRS transport
- REST/WebSocket API
- Database design

No production implementation exists yet.

---

# Roadmap

- [ ] Define system architecture
- [ ] Define application protocol
- [ ] Design APRS transport
- [ ] Design REST/WebSocket API
- [ ] Design database
- [ ] Implement server
- [ ] Implement Flutter client
- [ ] Add Packet support
- [ ] Add LoRa support
- [ ] Add VARA support

---

# Design Philosophy

OpenQSP is **not** an APRS application.

It is a transport-independent communication platform where APRS is one of several supported transports.

Every design decision prioritizes:

- Simplicity
- Reliability
- Low bandwidth usage
- Extensibility
- Long-term maintainability

---

# Contributing

OpenQSP is currently in its design stage.

Ideas, discussions and contributions are welcome as the architecture evolves.

---

# License

This project is licensed under the GNU General Public License v3.0 (GPL-3.0).
