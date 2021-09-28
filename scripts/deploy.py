from brownie import Resolver, ReNFT, accounts
from brownie.network.gas.strategies import GasNowStrategy


def main():

    a = accounts.load("")
    resolver = "0x945e589a4715d1915e6fe14f08e4887bc4019341"
    beneficiary = "0x28f11c3D76169361D22D8aE53551827Ac03360B0"
    gas_strategy = GasNowStrategy("fast")
    from_a = {"from": a, "gas_price": gas_strategy}
    _ = ReNFT.deploy(resolver, beneficiary, a.address, from_a)
