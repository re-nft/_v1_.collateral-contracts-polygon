from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import List

import pytest
import brownie
from brownie import (
    WETH,
    DAI,
    TUSD,
    USDC,
    E721,
    E1155,
    Resolver,
    ReNFT,
    accounts,
)
from brownie.test import strategy, contract_strategy

BILLION = Decimal("1_000_000_000e18")
SEPARATOR = "::"


class NFTStandard(Enum):
    E721 = 0
    E1155 = 1


class PaymentToken(Enum):
    SENTINEL = 0
    WETH = 1
    DAI = 2
    USDC = 3
    TUSD = 4


class Accounts:
    def __init__(self, accounts):
        self.deployer = accounts[0]
        self.beneficiary = accounts[1]
        self.lender = accounts[2]
        self.renter = accounts[3]

# reset state before each test


@pytest.fixture(autouse=True)
def shared_setup(fn_isolation):
    pass


@pytest.fixture(scope="module")
def A():
    A = Accounts(accounts)
    return A


@pytest.fixture(scope="module")
def payment_tokens(A):
    weth = WETH.deploy({"from": A.deployer})
    dai = DAI.deploy({"from": A.deployer})
    usdc = USDC.deploy({"from": A.deployer})
    tusd = TUSD.deploy({"from": A.deployer})
    return {1: weth, 2: dai, 3: usdc, 4: tusd}


@pytest.fixture(scope="module")
def resolver(A):
    resolver = Resolver.deploy(A.deployer, {"from": A.deployer})
    return resolver


@pytest.fixture(scope="module")
def nfts(A):
    for i in range(5):
        E721.deploy({"from": A.deployer})
    for i in range(5):
        E1155.deploy({"from": A.deployer})


def find_first(
    nft_standard: NFTStandard,
    lending_renting: dict,
    lender_blacklist: List[str] = None,
    id_blacklist: List[str] = None,
):
    if lender_blacklist is None:
        lender_blacklist = []

    if id_blacklist is None:
        id_blacklist = []

    for _id, lending_renting_instance in lending_renting.items():
        _, _, lending_id = _id.split(SEPARATOR)
        item = lending_renting_instance.lending
        if (
            (item.nft_standard == nft_standard) and
            (item.lender_address not in lender_blacklist) and
            (lending_id not in id_blacklist)
        ):
            return _id
    return ""


def find_from_lender(
    lender_address: str, nft_standard: NFTStandard, lending_renting: dict, not_in_id: List[str]
):
    for _id, lending_renting_instance in lending_renting.items():
        item = lending_renting_instance.lending
        if (
            item.nft_standard == nft_standard and
            item.lender_address == lender_address and
            _id not in not_in_id
        ):
            return _id
        return ""


def mint_and_approve(payment_token_contract, renter_address, registry_address):
    payment_token_contract.faucet({"from": renter_address})
    payment_token_contract.approve(registry_address, BILLION, {
                                   "from": renter_address})


@dataclass
class Lending:
    nft_standard: NFTStandard
    lender_address: str
    max_rent_duration: str
    daily_rent_price: bytes
    nft_price: bytes
    lent_amount: int
    payment_token: PaymentToken
    # below are not part of the contract struct
    nft: str
    token_id: int
    lending_id: int


@dataclass
class Renting:
    renter_address: str
    rent_duration: int
    rented_at: int
    # below are not part of the contract struct
    nft_standard: NFTStandard
    nft: str
    token_id: int
    lending_id: int


@dataclass
class LendingRenting:
    lending: Lending
    renting: Renting


def concat_lending_id(nft, token_id, lending_id):
    return f"{nft}{SEPARATOR}{token_id}{SEPARATOR}{lending_id}"


def lendings_to_lend_args(lendings):
    args = [[], [], [], [], [], [], [], []]
    for lending in lendings:
        args[0].append(lending.nft_standard)
        args[1].append(lending.nft)
        args[2].append(lending.token_id)
        args[3].append(lending.lent_amount)
        args[4].append(lending.max_rent_duration)
        args[5].append(lending.daily_rent_price)
        args[6].append(lending.nft_price)
        args[7].append(lending.payment_token)
    return args


def lendings_to_stop_lending_args(lendings):
    args = [[], [], [], []]
    for lending in lendings:
        args[0].append(lending.nft_standard)
        args[1].append(lending.nft)
        args[2].append(lending.token_id)
        args[3].append(lending.lending_id)
    return args


def rentings_to_rent_args(rentings):
    args = [[], [], [], [], []]
    for renting in rentings:
        args[0].append(renting.nft_standard)
        args[1].append(renting.nft)
        args[2].append(renting.token_id)
        args[3].append(renting.lending_id)
        args[4].append(renting.rent_duration)
    return args


class StateMachine:
    address = strategy("address")
    e721 = contract_strategy("E721")
    e1155 = contract_strategy("E1155")
    e1155_lent_amount = strategy("uint256", min_value="1", max_value="10")

    def __init__(cls, accounts, ReNFT, resolver, beneficiary, payment_tokens):
        cls.accounts = accounts
        cls.contract = ReNFT.deploy(
            resolver.address, beneficiary.address, accounts[0], {"from": accounts[0]})
        cls.payment_tokens = payment_tokens

    def setup(self):
        self.lending_renting = dict()

    def rule_lend_721(self, address, e721):
        print(f"rule_lend_721. a,e721. {address},{e721}")
        txn = e721.faucet({"from": address})
        e721.setApprovalForAll(self.contract.address, True, {"from": address})

        # todo: max_rent_duration is a strategy, and some cases revert
        lending = Lending(
            lender_address=address,
            nft_standard=NFTStandard.E721.value,
            lent_amount=1,
            max_rent_duration=1,
            daily_rent_price=1,
            nft_price=3,
            payment_token=PaymentToken.DAI.value,
            # not part of the contract's lending struct
            nft=e721.address,
            token_id=txn.events["Transfer"]["tokenId"],
            lending_id=0,
        )
        lending_renting = LendingRenting(lending, None)

        txn = self.contract.lend(
            *lendings_to_lend_args([lending]),
            {"from": address},
        )

        lending.lending_id = txn.events["Lent"]["lendingId"]
        self.lending_renting[
            concat_lending_id(lending.nft,
                              lending.token_id, lending.lending_id)
        ] = lending_renting

    def rule_lend_1155(self, address, e1155, e1155_lent_amount):
        print(f"rule_lend_1155. a,e1155. {address},{e1155}")
        txn = e1155.faucet({"from": address})
        e1155.setApprovalForAll(self.contract.address, True, {"from": address})

        # todo: max_rent_duration is a strategy, and some cases revert
        lending = Lending(
            lender_address=address,
            nft_standard=NFTStandard.E1155.value,
            lent_amount=e1155_lent_amount,
            max_rent_duration=1,
            daily_rent_price=1,
            nft_price=3,
            payment_token=PaymentToken.DAI.value,
            # not part of the contract's lending struct
            nft=e1155.address,
            token_id=txn.events["TransferSingle"]["id"],
            lending_id=0,
        )
        lending_renting = LendingRenting(lending, None)

        txn = self.contract.lend(
            *lendings_to_lend_args([lending]),
            {"from": address},
        )

        lending.lending_id = txn.events["Lent"]["lendingId"]
        self.lending_renting[
            concat_lending_id(lending.nft,
                              lending.token_id, lending.lending_id)
        ] = lending_renting

    def rule_lend_batch_721(self, address, e721a="e721", e721b="e721"):
        print(f"rule_lend_batch_721. a,e721. {address},{e721a},{e721b}")
        txna = e721a.faucet({"from": address})
        e721a.setApprovalForAll(self.contract.address, True, {"from": address})
        txnb = e721b.faucet({"from": address})
        e721b.setApprovalForAll(self.contract.address, True, {"from": address})

        # todo: max_rent_duration is a strategy, and some cases revert
        lendinga = Lending(
            lender_address=address,
            nft_standard=NFTStandard.E721.value,
            lent_amount=1,
            max_rent_duration=1,
            daily_rent_price=1,
            nft_price=3,
            payment_token=PaymentToken.DAI.value,
            # not part of the contract's lending struct
            nft=e721a.address,
            token_id=txna.events["Transfer"]["tokenId"],
            lending_id=0,
        )
        lending_rentinga = LendingRenting(lendinga, None)

        lendingb = Lending(
            lender_address=address,
            nft_standard=NFTStandard.E721.value,
            lent_amount=1,
            max_rent_duration=1,
            daily_rent_price=1,
            nft_price=3,
            payment_token=PaymentToken.DAI.value,
            # not part of the contract's lending struct
            nft=e721b.address,
            token_id=txnb.events["Transfer"]["tokenId"],
            lending_id=0,
        )
        lending_rentingb = LendingRenting(lendingb, None)

        txn = self.contract.lend(
            *lendings_to_lend_args([lendinga, lendingb]),
            {"from": address},
        )

        lendinga.lending_id = txn.events["Lent"][0]["lendingId"]
        self.lending_renting[
            concat_lending_id(lendinga.nft,
                              lendinga.token_id, lendinga.lending_id)
        ] = lending_rentinga

        lendingb.lending_id = txn.events["Lent"][1]["lendingId"]
        self.lending_renting[
            concat_lending_id(lendingb.nft,
                              lendingb.token_id, lendingb.lending_id)
        ] = lending_rentingb

    def rule_lend_batch_1155(self, address, e1155a="e1155", e1155b="e1155", e1155a_lent_amount="e1155_lent_amount", e1155b_lent_amount="e1155_lent_amount"):
        print(f"rule_lend_batch_1155. a,e1155. {address},{e1155a},{e1155b}")
        txna = e1155a.faucet({"from": address})
        e1155a.setApprovalForAll(
            self.contract.address, True, {"from": address})
        txnb = e1155b.faucet({"from": address})
        e1155b.setApprovalForAll(
            self.contract.address, True, {"from": address})

        # todo: max_rent_duration is a strategy, and some cases revert
        lendinga = Lending(
            lender_address=address,
            nft_standard=NFTStandard.E1155.value,
            lent_amount=e1155a_lent_amount,
            max_rent_duration=1,
            daily_rent_price=1,
            nft_price=3,
            payment_token=PaymentToken.DAI.value,
            # not part of the contract's lending struct
            nft=e1155a.address,
            token_id=txna.events["TransferSingle"]["id"],
            lending_id=0,
        )
        lending_rentinga = LendingRenting(lendinga, None)

        lendingb = Lending(
            lender_address=address,
            nft_standard=NFTStandard.E1155.value,
            lent_amount=e1155b_lent_amount,
            max_rent_duration=1,
            daily_rent_price=1,
            nft_price=3,
            payment_token=PaymentToken.DAI.value,
            # not part of the contract's lending struct
            nft=e1155b.address,
            token_id=txnb.events["TransferSingle"]["id"],
            lending_id=0,
        )
        lending_rentingb = LendingRenting(lendingb, None)

        txn = self.contract.lend(
            *lendings_to_lend_args([lendinga, lendingb]),
            {"from": address},
        )

        lendinga.lending_id = txn.events["Lent"][0]["lendingId"]
        self.lending_renting[
            concat_lending_id(lendinga.nft,
                              lendinga.token_id, lendinga.lending_id)
        ] = lending_rentinga

        lendingb.lending_id = txn.events["Lent"][1]["lendingId"]
        self.lending_renting[
            concat_lending_id(lendingb.nft,
                              lendingb.token_id, lendingb.lending_id)
        ] = lending_rentingb

    def rule_lend_batch_721_1155(self, address, e721a="e721", e721b="e721", e1155a="e1155", e1155b="e1155", e1155a_lent_amount="e1155_lent_amount", e1155b_lent_amount="e1155_lent_amount"):
        print(f"rule_lend_batch_721_1155. a,e1155,e721. {address},{e1155a},{e1155b},{e721a},{e721b}")
        txna = e1155a.faucet({"from": address})
        e1155a.setApprovalForAll(
            self.contract.address, True, {"from": address})
        txnb = e1155b.faucet({"from": address})
        e1155b.setApprovalForAll(
            self.contract.address, True, {"from": address})
        txnc = e721a.faucet({"from": address})
        e721a.setApprovalForAll(self.contract.address, True, {"from": address})
        txnd = e721b.faucet({"from": address})
        e721b.setApprovalForAll(self.contract.address, True, {"from": address})

        # todo: max_rent_duration is a strategy, and some cases revert
        lendinga = Lending(
            lender_address=address,
            nft_standard=NFTStandard.E1155.value,
            lent_amount=e1155a_lent_amount,
            max_rent_duration=1,
            daily_rent_price=1,
            nft_price=3,
            payment_token=PaymentToken.DAI.value,
            # not part of the contract's lending struct
            nft=e1155a.address,
            token_id=txna.events["TransferSingle"]["id"],
            lending_id=0,
        )
        lending_rentinga = LendingRenting(lendinga, None)

        lendingb = Lending(
            lender_address=address,
            nft_standard=NFTStandard.E1155.value,
            lent_amount=e1155b_lent_amount,
            max_rent_duration=1,
            daily_rent_price=1,
            nft_price=3,
            payment_token=PaymentToken.DAI.value,
            # not part of the contract's lending struct
            nft=e1155b.address,
            token_id=txnb.events["TransferSingle"]["id"],
            lending_id=0,
        )
        lending_rentingb = LendingRenting(lendingb, None)

        lendingc = Lending(
            lender_address=address,
            nft_standard=NFTStandard.E721.value,
            lent_amount=1,
            max_rent_duration=1,
            daily_rent_price=1,
            nft_price=3,
            payment_token=PaymentToken.DAI.value,
            # not part of the contract's lending struct
            nft=e721a.address,
            token_id=txnc.events["Transfer"]["tokenId"],
            lending_id=0,
        )
        lending_rentingc = LendingRenting(lendingc, None)

        lendingd = Lending(
            lender_address=address,
            nft_standard=NFTStandard.E721.value,
            lent_amount=1,
            max_rent_duration=1,
            daily_rent_price=1,
            nft_price=3,
            payment_token=PaymentToken.DAI.value,
            # not part of the contract's lending struct
            nft=e721b.address,
            token_id=txnd.events["Transfer"]["tokenId"],
            lending_id=0,
        )
        lending_rentingd = LendingRenting(lendingd, None)

        txn = self.contract.lend(
            *lendings_to_lend_args([lendinga, lendingb, lendingc, lendingd]),
            {"from": address},
        )

        lendinga.lending_id = txn.events["Lent"][0]["lendingId"]
        self.lending_renting[
            concat_lending_id(lendinga.nft,
                              lendinga.token_id, lendinga.lending_id)
        ] = lending_rentinga

        lendingb.lending_id = txn.events["Lent"][1]["lendingId"]
        self.lending_renting[
            concat_lending_id(lendingb.nft,
                              lendingb.token_id, lendingb.lending_id)
        ] = lending_rentingb

        lendingc.lending_id = txn.events["Lent"][2]["lendingId"]
        self.lending_renting[
            concat_lending_id(lendingc.nft,
                              lendingc.token_id, lendingc.lending_id)
        ] = lending_rentingc

        lendingd.lending_id = txn.events["Lent"][3]["lendingId"]
        self.lending_renting[
            concat_lending_id(lendingd.nft,
                              lendingd.token_id, lendingd.lending_id)
        ] = lending_rentingd

    def rule_stop_lending_721(self):
        first = find_first(NFTStandard.E721.value, self.lending_renting)
        if first == "":
            return
        print(f"rule_stop_lending_721.a,{first}")
        lending = self.lending_renting[first].lending
        renting = self.lending_renting[first].renting
        if renting is not None:
            with brownie.reverts("ReNFT::not a zero address"):
                self.contract.stopLending(
                    *lendings_to_stop_lending_args([lending]),
                    {"from": lending.lender_address},
                )
        else:
            self.contract.stopLending(
                *lendings_to_stop_lending_args([lending]),
                {"from": lending.lender_address},
            )
            del self.lending_renting[first]

    def rule_stop_lending_1155(self):
        first = find_first(NFTStandard.E1155.value, self.lending_renting)
        if first == "":
            return
        print(f"rule_stop_lending_1155.a,{first}")
        lending = self.lending_renting[first].lending
        renting = self.lending_renting[first].renting
        if renting is not None:
            with brownie.reverts("ReNFT::not a zero address"):
                self.contract.stopLending(
                    *lendings_to_stop_lending_args([lending]),
                    {"from": lending.lender_address},
                )
        else:
            self.contract.stopLending(
                *lendings_to_stop_lending_args([lending]),
                {"from": lending.lender_address},
            )
            del self.lending_renting[first]

    def rule_stop_lending_batch_721(self):
        first = find_first(NFTStandard.E721.value, self.lending_renting)
        if first == "":
            return
        lendinga = self.lending_renting[first].lending
        rentinga = self.lending_renting[first].renting

        second = find_from_lender(
            lendinga.lender_address, NFTStandard.E721.value, self.lending_renting, [
                first]
        )
        if second == "":
            return
        lendingb = self.lending_renting[second].lending
        rentingb = self.lending_renting[second].renting

        print(f"rule_stop_lending_batch_721.a,{first},{second}")

        if rentinga is not None or rentingb is not None:
            with brownie.reverts("ReNFT::not a zero address"):
                self.contract.stopLending(
                    *lendings_to_stop_lending_args([lendinga, lendingb]),
                    {"from": lending.lender_address},
                )
        else:
            self.contract.stopLending(
                *lendings_to_stop_lending_args([lendinga, lendingb]),
                {"from": lending.lender_address},
            )
            del self.lending_renting[first]
            del self.lending_renting[second]

    def rule_stop_lending_batch_1155(self):
        first = find_first(NFTStandard.E1155.value, self.lending_renting)
        if first == "":
            return
        lendinga = self.lending_renting[first].lending
        rentinga = self.lending_renting[first].renting

        second = find_from_lender(
            lendinga.lender_address, NFTStandard.E1155.value, self.lending_renting, [
                first]
        )
        if second == "":
            return
        lendingb = self.lending_renting[second].lending
        rentingb = self.lending_renting[second].renting

        print(f"rule_stop_lending_batch_1155.a,{first},{second}")

        if rentinga is not None or rentingb is not None:
            with brownie.reverts("ReNFT::not a zero address"):
                self.contract.stopLending(
                    *lendings_to_stop_lending_args([lendinga, lendingb]),
                    {"from": lending.lender_address},
                )
        else:
            self.contract.stopLending(
                *lendings_to_stop_lending_args([lendinga, lendingb]),
                {"from": lending.lender_address},
            )
            del self.lending_renting[first]
            del self.lending_renting[second]

    def rule_stop_lending_batch_721_1155(self):
        first = find_first(NFTStandard.E1155.value, self.lending_renting)
        if first == "":
            return
        lendinga = self.lending_renting[first].lending
        rentinga = self.lending_renting[first].renting

        second = find_from_lender(
            lendinga.lender_address, NFTStandard.E1155.value, self.lending_renting, [
                first]
        )
        if second == "":
            return
        lendingb = self.lending_renting[second].lending
        rentingb = self.lending_renting[second].renting

        third = find_from_lender(
            lendinga.lender_address, NFTStandard.E721.value, self.lending_renting, [
                first, second]
        )
        if third == "":
            return
        lendingc = self.lending_renting[third].lending
        rentingc = self.lending_renting[third].renting

        fourth = find_from_lender(
            lendinga.lender_address, NFTStandard.E721.value, self.lending_renting, [
                first, second, third]
        )
        if fourth == "":
            return
        lendingd = self.lending_renting[fourth].lending
        rentingd = self.lending_renting[fourth].renting

        print(f"rule_stop_lending_batch_721_1155.a,{first},{second},{third},{fourth}")

        if rentinga is not None or rentingb is not None or rentingc is not None or rentingd is not None:
            with brownie.reverts("ReNFT::not a zero address"):
                self.contract.stopLending(
                    *lendings_to_stop_lending_args([lendinga, lendingb]),
                    {"from": lending.lender_address},
                )
        else:
            self.contract.stopLending(
                *lendings_to_stop_lending_args([lendinga, lendingb]),
                {"from": lending.lender_address},
            )
            del self.lending_renting[first]
            del self.lending_renting[second]
            del self.lending_renting[third]
            del self.lending_renting[fourth]

    def rule_rent_721(self, address):
        first = find_first(
            NFTStandard.E721.value,
            self.lending_renting,
            lender_blacklist=[address],
        )
        if first == "":
            return
        print(f"rule_rent_721.a,{first}")
        lending = self.lending_renting[first].lending
        mint_and_approve(
            self.payment_tokens[lending.payment_token], address, self.contract.address
        )
        renting = Renting(
            renter_address=address,
            rent_duration=1,
            rented_at=0,
            # not part of the contract's renting struct
            nft_standard=lending.nft_standard,
            nft=lending.nft,
            token_id=lending.token_id,
            lending_id=lending.lending_id,
        )
        if self.lending_renting[first].renting is not None:
            with brownie.reverts("ReNFT::not a zero address"):
                txn = self.contract.rent(
                    *rentings_to_rent_args([renting]),
                    {"from": address},
                )
        else:
            txn = self.contract.rent(
                *rentings_to_rent_args([renting]),
                {"from": address},
            )
            self.lending_renting[first].renting = renting

    def rule_rent_1155(self, address):
        first = find_first(
            NFTStandard.E1155.value,
            self.lending_renting,
            lender_blacklist=[address],
        )
        if first == "":
            return
        print(f"rule_rent_1155.a,{first}")
        lending = self.lending_renting[first].lending
        mint_and_approve(
            self.payment_tokens[lending.payment_token], address, self.contract.address
        )
        renting = Renting(
            renter_address=address,
            rent_duration=1,
            rented_at=0,
            # not part of the contract's renting struct
            nft_standard=lending.nft_standard,
            nft=lending.nft,
            token_id=lending.token_id,
            lending_id=lending.lending_id,
        )
        if self.lending_renting[first].renting is not None:
            with brownie.reverts("ReNFT::not a zero address"):
                txn = self.contract.rent(
                    *rentings_to_rent_args([renting]),
                    {"from": address},
                )
        else:
            txn = self.contract.rent(
                *rentings_to_rent_args([renting]),
                {"from": address},
            )
            self.lending_renting[first].renting = renting

    def rule_rent_batch_721(self, address):
        first = find_first(
            NFTStandard.E721.value,
            self.lending_renting,
            lender_blacklist=[address],
        )
        if first == "":
            return

        lendinga = self.lending_renting[first].lending

        second = find_first(
            NFTStandard.E721.value,
            self.lending_renting,
            lender_blacklist=[address],
            id_blacklist=[lendinga.lending_id]
        )
        if second == "":
            return

        lendingb = self.lending_renting[second].lending

        print(f"rule_rent_batch_721.a,{first},{second}")
        mint_and_approve(
            self.payment_tokens[lendinga.payment_token], address, self.contract.address
        )
        mint_and_approve(
            self.payment_tokens[lendingb.payment_token], address, self.contract.address
        )
        rentinga = Renting(
            renter_address=address,
            rent_duration=1,
            rented_at=0,
            # not part of the contract's renting struct
            nft_standard=lendinga.nft_standard,
            nft=lendinga.nft,
            token_id=lendinga.token_id,
            lending_id=lendinga.lending_id,
        )
        rentingb = Renting(
            renter_address=address,
            rent_duration=1,
            rented_at=0,
            # not part of the contract's renting struct
            nft_standard=lendingb.nft_standard,
            nft=lendingb.nft,
            token_id=lendingb.token_id,
            lending_id=lendingb.lending_id,
        )

        if self.lending_renting[first].renting is not None or self.lending_renting[second].renting is not None:
            with brownie.reverts("ReNFT::not a zero address"):
                txn = self.contract.rent(
                    *rentings_to_rent_args([rentinga, rentingb]),
                    {"from": address},
                )
        else:
            txn = self.contract.rent(
                *rentings_to_rent_args([rentinga, rentingb]),
                {"from": address},
            )

            self.lending_renting[first].renting = rentinga
            self.lending_renting[second].renting = rentingb

    def rule_rent_batch_1155(self, address):
        first = find_first(
            NFTStandard.E1155.value,
            self.lending_renting,
            lender_blacklist=[address],
        )
        if first == "":
            return

        lendinga = self.lending_renting[first].lending

        second = find_first(
            NFTStandard.E1155.value,
            self.lending_renting,
            lender_blacklist=[address],
            id_blacklist=[lendinga.lending_id]
        )
        if second == "":
            return

        lendingb = self.lending_renting[second].lending

        print(f"rule_rent_batch_1155.a,{first},{second}")
        mint_and_approve(
            self.payment_tokens[lendinga.payment_token], address, self.contract.address
        )
        mint_and_approve(
            self.payment_tokens[lendingb.payment_token], address, self.contract.address
        )
        rentinga = Renting(
            renter_address=address,
            rent_duration=1,
            rented_at=0,
            # not part of the contract's renting struct
            nft_standard=lendinga.nft_standard,
            nft=lendinga.nft,
            token_id=lendinga.token_id,
            lending_id=lendinga.lending_id
        )
        rentingb = Renting(
            renter_address=address,
            rent_duration=1,
            rented_at=0,
            # not part of the contract's renting struct
            nft_standard=lendingb.nft_standard,
            nft=lendingb.nft,
            token_id=lendingb.token_id,
            lending_id=lendingb.lending_id
        )

        if self.lending_renting[first].renting is not None or self.lending_renting[second].renting is not None:
            with brownie.reverts("ReNFT::not a zero address"):
                txn = self.contract.rent(
                    *rentings_to_rent_args([rentinga, rentingb]),
                    {"from": address},
                )
        else:
            txn = self.contract.rent(
                *rentings_to_rent_args([rentinga, rentingb]),
                {"from": address},
            )

            self.lending_renting[first].renting = rentinga
            self.lending_renting[second].renting = rentingb

    def rule_rent_batch_721_1155(self, address):
        first = find_first(
            NFTStandard.E1155.value,
            self.lending_renting,
            lender_blacklist=[address],
        )
        if first == "":
            return

        lendinga = self.lending_renting[first].lending

        second = find_first(
            NFTStandard.E1155.value,
            self.lending_renting,
            lender_blacklist=[address],
            id_blacklist=[lendinga.lending_id]
        )
        if second == "":
            return

        lendingb = self.lending_renting[second].lending

        third = find_first(
            NFTStandard.E721.value,
            self.lending_renting,
            lender_blacklist=[address],
            id_blacklist=[lendinga.lending_id, lendingb.lending_id]
        )
        if third == "":
            return

        lendingc = self.lending_renting[third].lending

        fourth = find_first(
            NFTStandard.E721.value,
            self.lending_renting,
            lender_blacklist=[address],
            id_blacklist=[lendinga.lending_id,
                          lendingb.lending_id, lendingc.lending_id]
        )
        if fourth == "":
            return

        lendingd = self.lending_renting[fourth].lending

        print(f"rule_rent_batch_721_1155.a,{first},{second},{third},{fourth}")
        mint_and_approve(
            self.payment_tokens[lendinga.payment_token], address, self.contract.address
        )
        mint_and_approve(
            self.payment_tokens[lendingb.payment_token], address, self.contract.address
        )
        mint_and_approve(
            self.payment_tokens[lendingc.payment_token], address, self.contract.address
        )
        mint_and_approve(
            self.payment_tokens[lendingd.payment_token], address, self.contract.address
        )

        rentinga = Renting(
            renter_address=address,
            rent_duration=1,
            rented_at=0,
            # not part of the contract's renting struct
            nft_standard=lendinga.nft_standard,
            nft=lendinga.nft,
            token_id=lendinga.token_id,
            lending_id=lendinga.lending_id,
        )
        rentingb = Renting(
            renter_address=address,
            rent_duration=1,
            rented_at=0,
            # not part of the contract's renting struct
            nft_standard=lendingb.nft_standard,
            nft=lendingb.nft,
            token_id=lendingb.token_id,
            lending_id=lendingb.lending_id
        )
        rentingc = Renting(
            renter_address=address,
            rent_duration=1,
            rented_at=0,
            # not part of the contract's renting struct
            nft_standard=lendingc.nft_standard,
            nft=lendingc.nft,
            token_id=lendingc.token_id,
            lending_id=lendingc.lending_id
        )
        rentingd = Renting(
            renter_address=address,
            rent_duration=1,
            rented_at=0,
            # not part of the contract's renting struct
            nft_standard=lendingd.nft_standard,
            nft=lendingd.nft,
            token_id=lendingd.token_id,
            lending_id=lendingd.lending_id
        )

        if self.lending_renting[first].renting is not None or self.lending_renting[second].renting is not None or self.lending_renting[third].renting is not None or self.lending_renting[fourth].renting is not None:
            with brownie.reverts("ReNFT::not a zero address"):
                txn = self.contract.rent(
                    *rentings_to_rent_args([rentinga, rentingb, rentingc, rentingd]),
                    {"from": address},
                )
        else:
            txn = self.contract.rent(
                *rentings_to_rent_args([rentinga, rentingb, rentingc, rentingd]),
                {"from": address},
            )

            self.lending_renting[first].renting = rentinga
            self.lending_renting[second].renting = rentingb
            self.lending_renting[third].renting = rentingc
            self.lending_renting[fourth].renting = rentingd


def test_stateful(ReNFT, accounts, state_machine, nfts, resolver, payment_tokens):
    beneficiary = accounts.from_mnemonic(
        "test test test test test test test test test test test junk", count=1
    )
    resolver.setPaymentToken(
        PaymentToken.WETH.value, payment_tokens[PaymentToken.WETH.value]
    )
    resolver.setPaymentToken(
        PaymentToken.DAI.value, payment_tokens[PaymentToken.DAI.value]
    )
    resolver.setPaymentToken(
        PaymentToken.USDC.value, payment_tokens[PaymentToken.USDC.value]
    )
    resolver.setPaymentToken(
        PaymentToken.TUSD.value, payment_tokens[PaymentToken.TUSD.value]
    )
    state_machine(
        StateMachine, accounts, ReNFT, resolver, beneficiary, payment_tokens
    )
