from pyteal import *
from pyteal.ast.bytes import Bytes
from helpers import program


def approval_program():

    # locals
    local_opponent = Bytes("opponent")  # byteslice
    local_bet = Bytes("bet")  # uint64
    local_private_play = Bytes("private_play")  # byteslice
    local_play = Bytes("play")  # byteslice

    op_challenge = Bytes("challenge")
    op_accept = Bytes("accept")
    op_reveal = Bytes("reveal")

    @Subroutine(TealType.none)
    def reset(account: Expr):
        return Seq(
            App.localPut(account, local_opponent, Bytes("")),
            App.localPut(account, local_bet, Int(0)),
            App.localPut(account, local_private_play, Bytes("")),
            App.localPut(account, local_play, Bytes("")),
        )

    @Subroutine(TealType.uint64)
    def is_account_empty(account: Expr):
        return Return(
            And(
                App.localGet(account, local_opponent) == Bytes(""),
                App.localGet(account, local_bet) == Int(0),
                App.localGet(account, local_private_play) == Bytes(""),
                App.localGet(account, local_play) == Bytes(""),
            )
        )
    
    @Subroutine(TealType.uint64)
    def is_valid_play(play: Expr):
        first_ch = ScratchVar(TealType.bytes)
        return Seq(
            first_ch.store(Substring(play, Int(0), Int(1))),
            Return(
                Or(
                    first_ch.load() == Bytes("r"),
                    first_ch.load() == Bytes("p"),
                    first_ch.load() == Bytes("s"),
                )
            ),
        )

    @Subroutine(TealType.uint64)
    def play_value(p: Expr):
        first_letter = ScratchVar()
        return Seq(
            first_letter.store(Substring(p, Int(0), Int(1))),
            Return(
                Cond(
                    [first_letter.load() == Bytes("r"), Int(0)],
                    [first_letter.load() == Bytes("p"), Int(1)],
                    [first_letter.load() == Bytes("s"), Int(2)],
                )
            ),
        )

    @Subroutine(TealType.uint64)
    def get_winner_account_index(challanger_play: Expr, opponent_play: Expr):
        return Return(
            Cond(
                [challanger_play == opponent_play, Int(2)],  # a tie
                [(challanger_play + Int(1)) % Int(3) == opponent_play, Int(1)],  # opponent wins
                [(opponent_play + Int(1)) % Int(3) == challanger_play,Int(0),],  # challanger wins
            )
        )

    @Subroutine(TealType.none)
    def send_reward(account_index: Expr, amount: Expr):
        return Seq(
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
                {
                    TxnField.type_enum: TxnType.Payment,
                    TxnField.receiver: Txn.accounts[account_index],
                    TxnField.amount: amount,
                }
            ),
            InnerTxnBuilder.Submit(),
        )

    @Subroutine(TealType.none)
    def create_challenge():
        return Seq(
            Assert(
                And(
                    # check that we have two txn, one for the payment
                    Global.group_size() == Int(2),
                    Txn.group_index() == Int(0),

                    # security checks
                    Gtxn[1].close_remainder_to() == Global.zero_address(),
                    Gtxn[0].rekey_to() == Global.zero_address(),
                    Gtxn[1].rekey_to() == Global.zero_address(),
                    
                    # check 2nd txn is a payment for the bet
                    Gtxn[1].type_enum() == TxnType.Payment,
                    # check the reciver is the application
                    Gtxn[1].receiver() == Global.current_application_address(),
                    # check the amount == the amount of the challanger
                    Gtxn[1].amount() == App.localGet(Txn.accounts[1], local_bet),

                    # check that the challanger is opted in
                    App.optedIn(Txn.accounts[1], Global.current_application_id()),

                    # check that challanger account is the correct account
                    Txn.sender() == App.localGet(Txn.accounts[1], local_opponent),

                    # check hashed/private play
                    Txn.application_args.length() == Int(2),
                    is_valid_play(Txn.application_args[1]),
                )
            ),
            App.localPut(Txn.sender(), local_opponent, Txn.accounts[1]),
            App.localPut(Txn.sender(), local_bet, Gtxn[1].amount()),
            App.localPut(Txn.sender(), local_play, Txn.application_args[1]),
            Approve()
        )

    @Subroutine(TealType.none)
    def accept_challenge():
        return Seq(
            Assert(
                And(
                    # check that we have two txn, one for the payment
                    Global.group_size() == Int(2),
                    Txn.group_index() == Int(0),

                    # security checks
                    Gtxn[1].close_remainder_to() == Global.zero_address(),
                    Gtxn[0].rekey_to() == Global.zero_address(),
                    Gtxn[1].rekey_to() == Global.zero_address(),
                    
                    # check 2nd txn is a payment for the bet
                    Gtxn[1].type_enum() == TxnType.Payment,
                    # check the reciver is the application
                    Gtxn[1].receiver() == Global.current_application_address(),
                    

                    # check that the opponent is opted in
                    App.optedIn(Txn.accounts[1], Global.current_application_id()),

                    # check accounts avilability to play
                    is_account_empty(Txn.sender()),
                    is_account_empty(Txn.accounts[1]),

                    # check hashed/private play
                    Txn.application_args.length() == Int(2),
                )
            ),
            App.localPut(Txn.sender(), local_opponent, Txn.accounts[1]),
            App.localPut(Txn.sender(), local_bet, Gtxn[1].amount()),
            App.localPut(Txn.sender(), local_private_play, Txn.application_args[1]),
            Approve()
        )


    @Subroutine(TealType.none)
    def reveal():
        challenger_play = ScratchVar(TealType.uint64)
        opponent_play = ScratchVar(TealType.uint64)
        winner_index = ScratchVar(TealType.uint64)
        bet = ScratchVar(TealType.uint64)

        return Seq(
            Assert(
                And(
                    # check that we have one txn
                    Global.group_size() == Int(1),
                    Txn.group_index() == Int(0),

                    # security checks
                    Gtxn[0].rekey_to() == Global.zero_address(),

                    # check accounts are opponents to each other
                    App.localGet(Txn.sender(), local_opponent) == Txn.accounts[1],
                    App.localGet(Txn.accounts[1], local_opponent) == Txn.sender(),

                    # check accounts have the same bet
                    App.localGet(Txn.sender(), local_bet) == App.localGet(Txn.accounts[1], local_bet),

                    # check account has submit a play
                    App.localGet(Txn.sender(), local_private_play) != Bytes(""),
                    App.localGet(Txn.accounts[1], local_play) != Bytes(""),

                    # the private_play is valid
                    Txn.application_args.length() == Int(2),
                    Sha256(Txn.application_args[1]) == App.localGet(Int(0), local_private_play),

                )
            ),
            challenger_play.store(play_value(Txn.application_args[1])),
            opponent_play.store(play_value(App.localGet(Txn.accounts[1], local_play))),
            bet.store(App.localGet(Txn.sender(), local_bet)),
            winner_index.store(get_winner_account_index(challenger_play.load(), opponent_play.load())),
            If(
                winner_index.load() == Int(2)
            )
            .Then(Seq(
                send_reward(Txn.sender(), bet.load()),
                send_reward(Txn.accounts[1], bet.load())
            )).Else(Seq(
                send_reward(winner_index.load(), bet.load() * Int(2))
            )),
            reset(Txn.sender()),
            reset(Txn.accounts[1]),
            Approve()
        )

    return program.event(
        init=Approve(),
        opt_in=Seq(
            reset(Int(0)),
            Approve(),
        ),
        no_op=Seq(
            Cond(
                [
                    Txn.application_args[0] == op_challenge,
                    create_challenge(),
                ],
                [
                    Txn.application_args[0] == op_accept,
                    accept_challenge(),
                ],
                [
                    Txn.application_args[0] == op_reveal,
                    reveal(),
                ],
            ),
            Reject(),
        ),
    )


def clear_state_program():
    return Int(0)


if __name__ == "__main__":
    with open("vote_approval.teal", "w") as f:
        compiled = compileTeal(approval_program(), Mode.Application, version=6)
        f.write(compiled)

    with open("vote_clear_state.teal", "w") as f:
        compiled = compileTeal(clear_state_program(), Mode.Application, version=6)
        f.write(compiled)