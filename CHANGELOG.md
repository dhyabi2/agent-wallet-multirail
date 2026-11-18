# Changelog

## Unreleased (after 0.1.0)

A minor-version change for `swap.py` callers: behaviour below differs from 0.1.0.

### Changed

- `NanswapProvider` uses the plain endpoints with a ticker that names the
  chain (`USDC-BASE`). `from_network` is joined into the ticker; `to_network`
  is accepted and echoed on `SwapEstimate` but not sent.
- `NANSWAP_*_PARTNER` constants still import but now alias the plain paths
  (`/create-order`, ...), not the partner endpoints. A hand-built partner
  request posted to them goes to `/create-order` with the wrong body.
- With the default transport, `estimate`/`limits`/`order`/`create_order` raise
  `SwapRefused` instead of `urllib.error.HTTPError`/`URLError`. Every such
  refusal is also a `urllib.error.URLError` (and an `OSError`), so
  `except URLError` still catches it; read `exc.reason`, not `exc.code`.
- Redirects are never followed. A 3xx on the create-order POST is
  `order_unconfirmed`, and the `nanswap-api-key` header is never sent to the
  redirect target.
- A create-order whose outcome is unknown (3xx, 5xx, timeout, unreadable
  reply, an error reply carrying an order id at any status, or an exception
  from a custom provider that cannot be classified) leaves the `order_key`
  recorded as `order_unconfirmed`; 0.1.0 created the order again on retry.

### Added

- `release_pending_order_key(order_log, order_key)`: frees a key left
  `order_unconfirmed` once the provider shows no order. Refuses
  `order_key_not_releasable` for a key holding a created order or a send.
