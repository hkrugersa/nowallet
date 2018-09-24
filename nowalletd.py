import sys
import json
import asyncio

from decimal import Decimal
from aioconsole import ainput
from pycoin.tx.Tx import Tx

import nowallet

class WalletDaemon:
    def __init__(self, _loop, _salt, _passphrase):
        self.loop = _loop

        chain = nowallet.TBTC
        server, port, proto = nowallet.get_random_server(self.loop)
        connection = nowallet.Connection(self.loop, server, port, proto)

        self.wallet = nowallet.Wallet(_salt, _passphrase, connection, self.loop, chain)
        # self.wallet.bech32 = True
        self.wallet.discover_all_keys()
        self.print_history()
        self.wallet.new_history = False

    def print_history(self, last_only=False):
        history = list(map(lambda h: h.as_dict(), self.wallet.get_tx_history()))
        utxos = list(map(lambda u: u.as_dict(), self.wallet.utxos))
        output = {
            "tx_history": history[-1] if last_only else history,
            "utxos": utxos
        }
        print(json.dumps(output))

    async def input_loop(self):
        while True:
            input_ = await ainput(loop=self.loop)
            if not input_:
                continue
            if input_ == "@end":
                sys.exit(0)
            obj = json.loads(input_)
            self.dispatch_input(obj)

    async def new_history_loop(self):
        while True:
            await asyncio.sleep(1)
            if self.wallet.new_history:
                self.print_history(last_only=True)
                self.wallet.new_history = False

    def dispatch_input(self, obj):
        type_ = obj["type"]
        if type_ == "get_address":
            self.do_get_address()
        elif type_ == "get_feerate":
            self.do_get_feerate()
        elif type_ == "get_balance":
            self.do_get_balance()
        elif type_ == "get_ypub":
            self.do_get_ypub()
        elif type_ == "mktx":
            self.do_mktx(obj)
        elif type_ == "broadcast":
            self.do_broadcast(obj)

    def do_get_address(self):
        key = self.wallet.get_next_unused_key()
        address = self.wallet.get_address(key, addr=True)
        output = {"address": address}
        print(json.dumps(output))

    def do_get_feerate(self):
        feerate = self.wallet.get_fee_estimation()
        output = {"feerate": feerate}
        print(json.dumps(output))

    def do_get_balance(self):
        balances = {
            "confirmed": str(self.wallet.balance),
            "zeroconf": str(self.wallet.zeroconf_balance)
        }
        output = {"balance": balances}
        print(json.dumps(output))

    def do_get_ypub(self):
        output = {"ypub": self.wallet.ypub}
        print(json.dumps(output))

    def do_mktx(self, obj):
        address, amount, coin_per_kb = \
            obj["address"], Decimal(obj["amount"]), obj["feerate"]
        tx_hex, chg_vout, decimal_fee, tx_vsize = \
            self.wallet.spend(address, amount, coin_per_kb, rbf=True, broadcast=False)
        output = {
            "tx_hex": tx_hex,
            "vout": chg_vout,
            "fee": str(decimal_fee),
            "vsize": tx_vsize
        }
        print(json.dumps(output))

    def do_broadcast(self, obj):
        tx_hex, chg_vout = obj["tx_hex"], obj["vout"]
        chg_out = Tx.from_hex(tx_hex).txs_out[chg_vout]
        txid = self.wallet.broadcast(tx_hex, chg_out)
        output = {"txid": txid}
        print(json.dumps(output))

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    salt, passphrase = "foo1", "bar1"  # TODO: Get from user somehow
    daemon = WalletDaemon(loop, salt, passphrase)

    tasks = asyncio.gather(
        asyncio.ensure_future(daemon.wallet.listen_to_addresses()),
        asyncio.ensure_future(daemon.input_loop()),
        asyncio.ensure_future(daemon.new_history_loop())
    )

    # Graceful shutdown code borrowed from:
    # https://stackoverflow.com/questions/30765606/
    # whats-the-correct-way-to-clean-up-after-an-interrupted-event-loop
    try:
        # Here `amain(loop)` is the core coroutine that may spawn any
        # number of tasks
        sys.exit(loop.run_until_complete(tasks))

    except KeyboardInterrupt:
        # Optionally show a message if the shutdown may take a while
        print("\nAttempting graceful shutdown, press Ctrl+C again to exit...",
              flush=True)

        # Do not show `asyncio.CancelledError` exceptions during shutdown
        # (a lot of these may be generated, skip this if you prefer to see them)
        def shutdown_exception_handler(_loop, context):
            if "exception" not in context \
                    or not isinstance(context["exception"], asyncio.CancelledError):
                _loop.default_exception_handler(context)
        loop.set_exception_handler(shutdown_exception_handler)

        # Handle shutdown gracefully by waiting for all tasks to be cancelled
        tasks = asyncio.gather(*asyncio.Task.all_tasks(loop=loop),
                               loop=loop, return_exceptions=True)
        tasks.add_done_callback(lambda t: loop.stop())
        tasks.cancel()

        # Keep the event loop running until it is either destroyed or all
        # tasks have really terminated
        while not tasks.done() and not loop.is_closed():
            loop.run_forever()

    finally:
        loop.close()
