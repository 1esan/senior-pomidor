from __future__ import annotations

import argparse
import logging
import random
from datetime import datetime
from typing import TYPE_CHECKING

from ..ai.base import AIError
from ..api import ApiError, datatypes
from ..tool import BaseNamespace, BaseOperation
from ..utils.date import parse_api_datetime
from ..utils.string import rand_text

if TYPE_CHECKING:
    from ..tool import HHApplicantTool


try:
    import readline

    readline.add_history("/cancel ")
    readline.add_history("/ban")
    readline.set_history_length(10_000)
except ImportError:
    pass


DEFAULT_SYSTEM_PROMPT = (
    "Ты — соискатель на HeadHunter. Отвечай вежливо и кратко."
)
DEFAULT_USER_PROMPT = (
    "Напиши короткий ответ работодателю на основе истории переписки."
)


logger = logging.getLogger("hh-applicant-tool")


class Namespace(BaseNamespace):
    reply_message: str
    max_pages: int
    only_invitations: bool
    dry_run: bool
    system_prompt: str
    message_prompt: str
    period: int


class Operation(BaseOperation):
    """Ответ всем работодателям."""

    __aliases__ = ["reply-empls", "reply-chats", "reall"]

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--resume-id",
            help="Идентификатор резюме. Если не указан, то просматриваем чаты для всех резюме",
        )
        parser.add_argument(
            "-m",
            "--reply-message",
            "--reply",
            help="Отправить сообщение во все чаты. Если не передать сообщение, то нужно будет вводить его в интерактивном режиме.",  # noqa: E501
        )
        parser.add_argument(
            "--period",
            type=int,
            help="Игнорировать отклики, которые не обновлялись больше N дней",
        )
        parser.add_argument(
            "-p",
            "--max-pages",
            type=int,
            default=25,
            help="Максимальное количество страниц для проверки",
        )
        parser.add_argument(
            "-oi",
            "--only-invitations",
            help="Отвечать только на приглашения",
            default=False,
            action=argparse.BooleanOptionalAction,
        )
        parser.add_argument(
            "--dry-run",
            "--dry",
            help="Не отправлять сообщения, а только выводить параметры запроса",
            default=False,
            action=argparse.BooleanOptionalAction,
        )
        parser.add_argument(
            "--system-prompt",
            "--ai-system",
            help="Системный промпт для AI",
        )
        parser.add_argument(
            "--message-prompt",
            "--prompt",
            help="Промпт для генерации сообщения",
        )

    def run(self, tool: HHApplicantTool, args: Namespace) -> None:
        self.tool = tool
        if not callable(getattr(tool, "employer_contact_guard", None)):
            raise RuntimeError("Запускайте ответы через hh.py: обязательна проверка запретов работодателей")
        self.api_client = tool.api_client
        # self.resume_id = tool.first_resume_id() #вместо id первого резюме берем id из аргументов
        self.resume_id = args.resume_id
        self.reply_message = args.reply_message or tool.config.get(
            "reply_message"
        )
        self.max_pages = args.max_pages
        self.dry_run = args.dry_run
        self.only_invitations = args.only_invitations

        self.message_prompt = args.message_prompt

        self.reply_chat_ai = None
        if args.use_ai:
            c = tool.get_openai_args("openai.reply_chat")
            c.setdefault("system_prompt", DEFAULT_SYSTEM_PROMPT)
            if args.system_prompt:
                c["system_prompt"] = args.system_prompt

            self.reply_chat_ai = tool.get_ai_client(**c)

        self.period = args.period
        logger.debug(f"{self.reply_message = }")
        return self.reply_employers()

    def reply_employers(self):
        blacklist = set(self.tool.get_blacklisted())
        me: datatypes.User = self.tool.get_me()
        resumes = self.tool.get_resumes()
        resumes = (
            list(filter(lambda x: x["id"] == self.resume_id, resumes))
            if self.resume_id is not None  # добавляем проверку на пустоту
            else resumes
        )
        resumes = list(
            filter(
                lambda resume: resume["status"]["id"] == "published", resumes
            )
        )
        if not resumes:
            logger.error("Нет опубликованных резюме")
            return 1
        return self._reply_chats(user=me, resumes=resumes, blacklist=blacklist)

    def _reply_chats(
        self,
        user: datatypes.User,
        resumes: list[datatypes.Resume],
        blacklist: set[str],
    ) -> None:
        from employer_guard import ContactBlocked
        resume_map = {r["id"]: r for r in resumes}

        base_placeholders = {
            "first_name": user.get("first_name") or "",
            "last_name": user.get("last_name") or "",
            "email": user.get("email") or "",
            "phone": user.get("phone") or "",
        }

        for index,negotiation in enumerate(self.tool.get_negotiations()):
            if index>=getattr(self,"max_pages",25)*100:break
            try:
                # try:
                #     self.tool.storage.negotiations.save(negotiation)
                # except RepositoryError as e:
                #     logger.exception(e)

                if "resume" not in negotiation:
                    continue

                if not (
                    resume := resume_map.get(negotiation["resume"].get("id"))
                ):
                    continue

                updated_at = parse_api_datetime(negotiation["updated_at"])

                # Пропуск откликов, которые не обновлялись более N дней (при просмотре они обновляются вроде)
                if (
                    self.period
                    and (datetime.now(updated_at.tzinfo) - updated_at).days
                    > self.period
                ):
                    continue

                state_id = negotiation["state"]["id"]
                if state_id == "discard":
                    continue

                if self.only_invitations and state_id not in ("invitation","interview"):
                    continue

                nid = negotiation["id"]
                vacancy = negotiation["vacancy"]
                employer = vacancy.get("employer") or {}
                salary = vacancy.get("salary") or {}
                full_vacancy=self.tool.employer_contact_guard(vacancy)

                if employer.get("id") in blacklist:
                    print(
                        "🚫 Пропускаем заблокированного работодателя",
                        employer.get("alternate_url"),
                    )
                    continue

                placeholders = {
                    "vacancy_name": vacancy.get("name", ""),
                    "vacancy_url": vacancy.get("alternate_url") or "",
                    "employer_name": employer.get("name", ""),
                    "resume_title": resume.get("title") or "",
                    **base_placeholders,
                }

                logger.debug(
                    "Вакансия %(vacancy_name)s от %(employer_name)s"
                    % placeholders
                )

                page: int = 0
                last_message: datatypes.Message | None = None
                message_history: list[str] = []
                all_messages=[]
                while True:
                    messages_res: datatypes.PaginatedItems[
                        datatypes.Message
                    ] = self.api_client.get(
                        f"/negotiations/{nid}/messages", page=page
                    )
                    if not messages_res["items"]:
                        break

                    all_messages.extend(messages_res["items"])
                    last_message = max(all_messages,key=lambda m:(m.get("created_at") or "",str(m.get("id") or "")))
                    for message in messages_res["items"]:
                        if not message.get("text"):
                            continue
                        author = (
                            "Работодатель"
                            if message["author"]["participant_type"]
                            == "employer"
                            else "Я"
                        )
                        message_date = parse_api_datetime(
                            message.get("created_at")
                        ).strftime("%d.%m.%Y %H:%M:%S")

                        message_history.append(
                            f"[ {message_date} ] {author}: {message['text']}"
                        )

                    if page + 1 >= messages_res["pages"]:
                        break
                    page += 1

                all_messages.sort(key=lambda m:(m.get("created_at") or "",str(m.get("id") or "")))
                message_history=[("Работодатель: " if (m.get("author") or {}).get("participant_type")=="employer" else "Я: ")+(m.get("text") or "") for m in all_messages if m.get("text")]
                self.tool.employer_contact_guard(vacancy, "\n".join(message_history))
                if not last_message:
                    continue

                is_employer_message = (
                    last_message["author"]["participant_type"] == "employer"
                )

                # Local adaptation: no proactive reply, one response per employer message.
                from pathlib import Path
                import json
                state_path = self.tool.config_dir_path / "replied.json"
                try:
                    reply_state = json.loads(state_path.read_text())
                except (FileNotFoundError, ValueError):
                    reply_state = {}
                message_id = str(last_message.get("id") or "")
                if str(reply_state.get(str(nid),"")).startswith("pending:"):
                    logger.warning("Чат %s: прерванная отправка требует ручной проверки",nid)
                    continue
                if is_employer_message and message_id and reply_state.get(str(nid)) != message_id:
                    send_message = ""
                    if self.reply_message:
                        send_message = (
                            rand_text(self.reply_message) % placeholders
                        )
                        logger.debug(f"Template message: {send_message}")
                    elif self.reply_chat_ai:
                        try:
                            ai_query = (
                                f"Вакансия: {placeholders['vacancy_name']}\n"
                                f"Описание: {full_vacancy.get("description","") if isinstance(full_vacancy,dict) else ""}\n"
                                f"История переписки:\n"
                                + "\n".join(message_history[-10:])
                                + f"\n\nИнструкция: {self.message_prompt}"
                            )
                            send_message = self.reply_chat_ai.complete(ai_query)
                            logger.debug(f"AI message: {send_message}")
                        except AIError as ex:
                            logger.warning(
                                f"Ошибка OpenAI для чата {nid}: {ex}"
                            )
                            continue
                    else:
                        print("🏢", placeholders["employer_name"])
                        print("💼", placeholders["vacancy_name"])
                        if salary:
                            print(
                                "💵 от",
                                salary.get("from") or salary.get("to") or 0,
                                "до",
                                salary.get("to") or salary.get("from") or 0,
                                salary.get("currency", "RUR"),
                            )

                        print("\nПоследние сообщения чата:")
                        print()
                        for msg in (
                            message_history[-5:]
                            if len(message_history) > 5
                            else message_history
                        ):
                            print(msg)

                        try:
                            print("-" * 40)
                            print("Активное резюме:", resume.get("title") or "")
                            print(
                                "/ban, /cancel необязательное сообщение для отмены"
                            )
                            send_message = input("Ваше сообщение: ").strip()
                        except EOFError:
                            continue

                        if not send_message:
                            print("🚶 Пропускаем чат")
                            continue

                        if send_message.startswith("/ban"):
                            self.api_client.put(
                                f"/employers/blacklisted/{employer['id']}"
                            )
                            blacklist.add(employer["id"])
                            print(
                                "🚫 Работодатель заблокирован",
                                employer.get("alternate_url"),
                            )
                            continue
                        elif send_message.startswith("/cancel"):
                            _, decline_msg = send_message.split("/cancel", 1)
                            self.api_client.delete(
                                f"/negotiations/active/{nid}",
                                with_decline_message=decline_msg.strip(),
                            )
                            print("❌ Отмена заявки", vacancy["alternate_url"])
                            continue

                    # Повторная проверка актуального профиля/адресата перед отправкой.
                    self.tool.employer_contact_guard(vacancy, "\n".join(message_history))
                    from candidate import reply_problem
                    if issue:=reply_problem(send_message):
                        logger.warning("Ответ требует проверки: %s",issue)
                        continue
                    if not send_message.strip():continue
                    # Финальная отправка текста
                    if self.dry_run:
                        logger.debug(
                            "dry-run: отклик на %s: %s",
                            vacancy["alternate_url"],
                            send_message,
                        )
                        print(f"Предпросмотр ответа {nid}: {send_message}")
                        callback=getattr(self.tool,"reply_result",None)
                        if callable(callback):callback(nid,message_id,send_message,True)
                        continue

                    reply_state[str(nid)]="pending:"+message_id
                    from runtime import save_json
                    save_json(state_path,reply_state)
                    self.api_client.post(
                        f"/negotiations/{nid}/messages",
                        message=send_message,
                        delay=random.uniform(1, 3),
                    )
                    reply_state[str(nid)] = message_id
                    save_json(state_path,reply_state)
                    callback=getattr(self.tool,"reply_result",None)
                    if callable(callback):callback(nid,message_id,send_message,False)
                    print(f"📨 Отправлено для {vacancy['alternate_url']}")

            except ContactBlocked as ex:
                logger.warning("Контакт заблокирован: %s", ex)
                continue
            except ApiError as ex:
                logger.error(ex)

        print("Предпросмотр ответов завершён" if getattr(self,"dry_run",True) else "Обработка ответов завершена")
