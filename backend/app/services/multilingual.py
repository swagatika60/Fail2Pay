"""Multilingual Communication Support.

Supports: English, Hindi, Hinglish, Odia
- Preserves customer language preference
- Same intent taxonomy across languages
- Natural responses (not word-for-word translation)
- Language never changes safety rules

Architecture:
  1. Detect language from customer message
  2. Use language-specific patterns for intent classification
  3. Respond in customer's language
  4. Store language preference in conversation metadata
"""

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# --- Supported Languages ---

SUPPORTED_LANGUAGES = {"en", "hi", "hi-en", "or"}

LANGUAGE_NAMES = {
    "en": "English",
    "hi": "Hindi",
    "hi-en": "Hinglish",
    "or": "Odia",
}


@dataclass
class LanguagePatterns:
    """Intent classification patterns for a specific language."""

    stop: list[str] = field(default_factory=list)
    already_paid: list[str] = field(default_factory=list)
    negative: list[str] = field(default_factory=list)
    promise_to_pay: list[str] = field(default_factory=list)
    payment_retry: list[str] = field(default_factory=list)
    payment_link: list[str] = field(default_factory=list)
    invoice: list[str] = field(default_factory=list)
    payment_plan: list[str] = field(default_factory=list)
    question: list[str] = field(default_factory=list)
    support: list[str] = field(default_factory=list)


# --- Language-Specific Patterns ---

PATTERNS: dict[str, LanguagePatterns] = {
    "en": LanguagePatterns(
        stop=[
            r"\bstop\b", r"\bunsubscribe\b", r"\bdon'?t\s*contact\b",
            r"\bleave\s*me\s*alone\b", r"\bdo\s*not\s*call\b",
        ],
        already_paid=[
            r"\balready\s*paid\b", r"\bpayment\s*(is\s*)?done\b",
            r"\bpaid\s*(already|yesterday|today|just)?\b", r"\bcompleted\s*payment\b",
            r"\btransaction\s*(is\s*)?(done|complete)\b",
        ],
        negative=[
            r"\bnot\s*paying\b", r"\bwill\s*not\s*pay\b", r"\bwon'?t\s*pay\b",
            r"\brefuse\b", r"\bfraud\b", r"\bscam\b",
        ],
        promise_to_pay=[
            r"\bi'?ll\s*pay\b", r"\bwill\s*pay\b", r"\bpromise\b",
            r"\bpay\s*(tomorrow|soon|by\s*\w+|within)\b",
            r"\bpay\s*later\b",
            r"\bpay\s*in\s*\d+\s*days?\b",
            r"\b(need|want|give)\s*\d+\s*days?\b",
            r"\bsure\s*i\s*will\b", r"\bdefinitely\b", r"\bpaying\b",
        ],
        payment_retry=[
            r"\bretry\b", r"\btry\s*(again|paying)\b", r"\battempt\s*(again|payment)\b",
            r"\bre\s*pay\b", r"\bpay\s*again\b", r"\bredo\s*payment\b",
        ],
        payment_link=[
            r"\b(send|share|give)\b.*\blink\b", r"\bpayment\s*link\b",
            r"\blink\s*(please|now|again)\b", r"\burl\b.*\bpay\b",
        ],
        invoice=[
            r"\binvoice\b", r"\bbill\b", r"\breceipt\b", r"\bstatement\b",
        ],
        payment_plan=[
            r"\b(installment|payment\s*plan|emi)\b", r"\bpay\s*in\s*\d+\s*(parts|installments)\b",
            r"\bsplit\b.*\bpayment\b", r"\bmonthly\b.*\bpay\b",
            r"\bpay\s*in\s*installments\b", r"\bin\s*installments\b",
            r"\bpay(?:ing)?\s*(?:a\s*)?part\s*\d+\b",
            r"\bpart\s*\d+\b.*\bin\s*\d+\s*installments?\b",
            r"\bnow\s*in\s*\d+\s*installments?\b",
        ],
        question=[
            r"\?$", r"\bwhy\b", r"\bwhat\b", r"\bhow\b", r"\bwhen\b",
            r"\bwhere\b", r"\bwho\b", r"\bcan\s*you\b", r"\bcould\s*you\b",
        ],
        support=[
            r"\btalk\s*to\s*(support|human|agent|someone)\b",
            r"\bhuman\s*(agent|support|representative)\b",
            r"\bcustomer\s*service\b", r"\bspeak\s*to\s*(someone|a\s*person)\b",
            r"\bhelp\s*from\s*(a\s*)?(human|person|agent)\b",
        ],
    ),
    "hi": LanguagePatterns(
        # Hindi (Devanagari script)
        stop=[
            r"\u092E\u0948\u0902 \u0939\u092E\u0947\u0902",  # मैं हमें (stop us)
            r"\u092E\u0947\u0938\u0947\u091C\b",  # मेसेज (message)
            r"\u092C\u0902\u0926\s*\u0928\u0939\u0940\u0902",  # बंद नहीं (don't stop)
            r"\u0938\u0902\u092A\u0930\u094D\u0915\b", r"\u092E\u0938\u093E\u091C\u094D",  # संपर्क (contact)
        ],
        already_paid=[
            r"\u092A\u0948\u0938\u093E\s*\u092D\u0930\s*\u091A\u0941\u0915\u093E",  # पैसा भर चुका
            r"\u092A\u0947\u092E\u0947\u0902\u091F\s*\u0939\u094B\su0917\u092F\u093E",  # पेमेंट हो गया
            r"\u091A\u0941\u0915\s*\u0917\u092F\u093E",  # चुक गया
            r"\u092A\u0947\u0921\u093C \u0926\u093F\u092F\u093E",  # पैड दिया
        ],
        negative=[
            r"\u0928\u0939\u0940\u0902 \u092A\u0947\u0928\u0947\u0902\u0917\u0947",  # नहीं पेनेंगे
            r"\u092A\u0948\u0938\u093E\s*\u0928\u0939\u0940\u0902 \u0926\u0942\u0902\u0917\u093E",  # पैसा नहीं दूंगा
            r"\u092B\u094D\u0930\u0949\u095C",  # फ्रॉड
            r"\u0938\u094D\u0915\u0948\u092E",  # स्केम
        ],
        promise_to_pay=[
            r"\u092E\u0948\u0902\s*\u092A\u0947\u092F\u093C\u0947\u0902\u0917\u093E",  # मैं पेयेंगा
            r"\u0915\u0932\b",  # कल (tomorrow)
            r"\u092E\u0948\u0902\s*\u0926\u0947\u0928\u0917\u0947",  # मैं देंगे
            r"\u092A\u0915\u094D\u0915\u093E",  # पक्का (sure)
            r"\u091C\u0930\u0942\u0930",  # जरूर (definitely)
            r"\u092E\u0948\u0902\s*\u0915\u0930\u0942\u0902\u0917\u093E",  # मैं करूंगा
        ],
        payment_retry=[
            r"\u092B\u093F\u0930\s*\u0938\u0947\s*\u092A\u0947\u092F\u093C\u0947\u0902\u0917\u0947",  # फिर से पेयेंगे
            r"\u0926\u094B\u092C\u093E\u0930\u093E\s*\u092A\u0947\u092F\u093C\u0947\u0902\u0917\u0947",  # दोबारा पेयेंगे
            r"\u0930\u0940\u091F\u094D\u0930\u093E\u0907",  # रीटराइ
        ],
        payment_link=[
            r"\u0932\u093F\u0902\u0915\b",  # लिंक
            r"\u092A\u0947\u092F\u093C\u092E\u0947\u0902\u091F\s*\u0932\u093F\u0902\u0915",  # पेमेंट लिंक
            r"\u092D\u0947\u091C\u094B",  # भेजो (send)
        ],
        invoice=[
            r"\u0907\u0928\u094D\u0935\u0949\u0938",  # इन्वॉइस
            r"\u092C\u093F\u0932",  # बिल
            r"\u0930\u0938\u0940\u092A\u094D\u091F",  # रसीप्ट
        ],
        payment_plan=[
            r"\u0915\u093F\u0938\u094D\u0924\u093E\u0902",  # किस्तां (installments)
            r"\u092A\u0947\u092F\u093C\u092E\u0947\u0902\u091F\s*\u092A\u094D\u0932\u093E\u0928",  # पेमेंट प्लान
            r"\u0907\u092E\u090F",  # ईएमआई
            r"\u092E\u0939\u0940\u0928\u093E\u0928\u0947\s*\u092A\u0947\u092F\u093C\u0947\u0902\u0917\u0947",  # महीनाने पेयेंगे
        ],
        question=[
            r"\u0915\u094D\u092F\u093E",  # क्या
            r"\u0915\u094D\u092F\u094B\u0902",  # क्यों
            r"\u0915\u0948\u0938\u0947",  # कैसे
            r"\u0915\u0939\u093E\u0902",  # कहां
            r"\u0915\u092C",  # कब
        ],
    ),
    "hi-en": LanguagePatterns(
        # Hinglish (Roman script with Hindi words)
        stop=[
            r"\bstop\b", r"\bband\s*karo\b", r"\bmess mat\s*karo\b",
            r"\bcontact\s*mat\s*karo\b", r"\bmessage\s*mat\s*bhejo\b",
        ],
        already_paid=[
            r"\bpaisa\s*bhar\s*chuka\b", r"\bpayment\s*ho\s*giya\b",
            r"\bpay\s*kar\s*diya\b", r"\bde\s*diya\b", r"\bdone\b",
        ],
        negative=[
            r"\bnahi\s*dunga\b", r"\bnahi\s*pay\s*karo*unga\b",
            r"\bpaisa\s*nahi\b", r"\bfraud\b", r"\bscam\b",
        ],
        promise_to_pay=[
            r"\bkal\b.*\b(karo*unga|de\s*dunga|pay\s*karo*unga|kar\s*dunga)\b", r"\bkal\s*de\s*dunga\b",
            r"\bmain\b.*\bkaro*unga\b", r"\bpakka\b", r"\bdefinitely\b",
            r"\bjarur\b", r"\bho\s*giya\b",
            r"\bpay\s*later\b", r"\blater\s*mein\b",
            r"\bpay\s*in\s*\d+\s*days?\b", r"\b(need|want)\s*\d+\s*days?\b",
        ],
        payment_retry=[
            r"\bphir\s*se\b", r"\bdobara\b", r"\bretry\b",
            r"\btry\s*again\b", r"\bwapas\s*pay\b",
        ],
        payment_link=[
            r"\blink\s*bhejo\b", r"\blink\s*do\b", r"\blink\s*chahiye\b",
            r"\bpayment\s*link\b", r"\bpay\s*ka\s*link\b",
        ],
        invoice=[
            r"\binvoice\b", r"\bbill\b", r"\breceipt\b",
        ],
        payment_plan=[
            r"\bkistom\s*mein\b", r"\bemi\s*mein\b", r"\binstallment\b",
            r"\bplan\s*banao\b", r"\bsplit\s*karo\b",
        ],
        question=[
            r"\?$", r"\bkyun\b", r"\bkyaa\b", r"\bkaise\b",
            r"\bkab\b", r"\bkahan\b",
        ],
    ),
    "or": LanguagePatterns(
        # Odia (Odia script)
        stop=[
            r"\u092E\u0938\u093E\u091C\u094D",  # ମସାଜ
            r"\u092C\u0928\u094D\u0926\b",  # ବନ୍ଦ
            r"\u0938\u092E\u094D\u092A\u0930\u094D\u0915",  # ସମ୍ପର୍କ
        ],
        already_paid=[
            r"\u092A\u0948\u0938\u093E\s*\u0926\u093F\u0907\u0932\u093E",  # ପୈସା ଦିଲା
            r"\u092A\u0947\u092E\u0947\u0902\u091F\s*\u0939\u0947\u0901\u093F",  # ପେମେଣ୍ଟ ହେଣ୍ଟି
            r"\u0939\u094B\u0901\u093F\u0917\u093E",  # ହୋଇଗା
        ],
        negative=[
            r"\u092A\u0948\u0938\u093E\s*\u0926\u0947\u092C\u093F\u0928\u093F",  # ପୈସା ଦେବିନି
            r"\u0928\u093E\u0939\u093F\u0901",  # ନାହିଂ
            r"\u09AB\u094D\u0930\u0949\u095C",  # ଫ୍ରଡ
        ],
        promise_to_pay=[
            r"\u092A\u093E\u0901\u093F\u0930\u093F",  # ପାଣିରି (tomorrow)
            r"\u092E\u0941\u0901\u093F\s*\u0926\u0947\u092C\u093F",  # ମୁନି ଦେବି
            r"\u0915\u0930\u093F\u092C\u093F",  # କରିବି
            r"\u0928\u093F\u0936\u094D\u091A\u093F\u0924",  # ନିଶ୍ଚିତ
        ],
        payment_retry=[
            r"\u092A\u0941\u0923\u093F\s*\u092A\u093E\u0931\u093F\u092C\u093F",  # ପୁଣି ପାରିବି
            r"\u0930\u093F\u091F\u094D\u0930\u093E\u0907",  # ରିଟରାଇ
        ],
        payment_link=[
            r"\u0932\u093F\u0902କ",  # ଲିଂକ
            r"\u092A\u0947\u092F\u093C\s*\u0932\u093F\u0902କ",  # ପେୟ ଲିଂକ
            r"\u092A\u093E\u0931\u093F\u092C\u093F",  # ପାରିବି
        ],
        invoice=[
            r"\u0907\u0928\u094D\u0935\u0949\u0938",  # ଇନ୍ଭଅିସ
            r"\u09AC\u093F\u0932",  # ବିଲ
        ],
        payment_plan=[
            r"\u0915\u093F\u0938\u094D\u0924\u093E",  # କିସ୍ତା
            r"\u092A\u094D\u0932\u093E\u0928",  # ପ୍ଲାନ
        ],
        question=[
            r"\u0915\u093F",  # କି (what)
            r"\u0915\u0947\u0928",  # କେନ (why)
            r"\u0915\u093F\u092E\u093F",  # କିମି (how)
            r"\u0915\u0947\u0924\u0947",  # କେତେ (when)
            r"\?$",
        ],
    ),
}


# --- Response Templates per Language ---

RESPONSE_TEMPLATES: dict[str, dict[str, str]] = {
    "en": {
        "payment_link": (
            "Here's your payment link to complete the payment of {amount}:\n{payment_link}\n\n"
            "If you need any help, just reply to this message."
        ),
        "invoice": (
            "Here's your invoice for the pending payment of {amount}:\n{invoice_link}\n\n"
            "Let us know if you have any questions."
        ),
        "already_paid": (
            "Thank you for letting us know. We're checking your payment status now.\n\n"
            "If your payment is confirmed, you'll receive a confirmation shortly. "
            "If there's any issue, we'll reach out to help you resolve it."
        ),
        "promise_to_pay": (
            "Thank you for confirming! We've noted your promise to pay.\n\n"
            "We'll follow up as scheduled. If you'd like to pay now, you can use this link:\n{payment_link}\n\n"
            "Need a payment plan? Just let us know."
        ),
        "payment_plan": (
            "We understand you'd like to set up a payment plan.\n\n"
            "We can split your payment of {amount} into manageable installments. "
            "Our team will reach out shortly with specific plan options.\n\n"
            "In the meantime, you can also pay the full amount here:\n{payment_link}"
        ),
        "question": (
            "Thanks for your question. Here's what you need to know:\n\n"
            "• Your pending payment is {amount}\n"
            "• You can pay anytime using this link: {payment_link}\n"
            "• If you need detailed help, our support team is available\n\n"
            "Is there anything else we can help with?"
        ),
        "negative": (
            "We understand your concern and we're sorry for the inconvenience.\n\n"
            "We've noted your feedback. If you'd like to discuss this further or "
            "need assistance with your payment, please reply to this message.\n\n"
            "We're here to help."
        ),
        "stop": (
            "We've noted your request to stop receiving messages.\n\n"
            "You will no longer receive payment reminders from us. "
            "If you have any outstanding payments, you can still pay at any time."
        ),
        "unclear": (
            "Thanks for your message. We want to make sure we understand correctly.\n\n"
            "Could you let us know:\n"
            "• Would you like to make a payment?\n"
            "• Do you need a payment link?\n"
            "• Or is there something else we can help with?\n\n"
            "Your pending payment is {amount}. You can pay here: {payment_link}"
        ),
        "payment_retry": (
            "You can retry your payment of {amount} using this link:\n{payment_link}\n\n"
            "If the payment fails again, please let us know and we'll help you troubleshoot."
        ),
        # Recovery Specialist intents
        "pay_now": (
            "Here is your direct link to settle the balance of {amount}:\n{payment_link}\n\n"
            "Tap it anytime to complete your payment."
        ),
        "split_emi": (
            "We can split your payment of {amount} into manageable installments.\n\n"
            "Use this link to activate your plan:\n{payment_link}"
        ),
        "pay_later": (
            "No problem! We've paused reminders for you.\n\n"
            "Your payment link for {amount} stays active:\n{payment_link}\n\n"
            "When would you like to pay? Just reply with a date."
        ),
        "greeting": (
            "Hello! I'm here to help with your pending payment of {amount}.\n\n"
            "Would you like to complete the payment or split it into installments?"
        ),
        "fallback": (
            "I'm sorry, I didn't quite catch that.\n\n"
            "Would you like to pay the full balance, split it into installments, "
            "or talk to support? Your pending payment is {amount}: {payment_link}"
        ),
        "support": (
            "I'm connecting you with our human support team right now.\n\n"
            "Someone will join this chat within 2-3 minutes or reply here directly."
        ),
    },
    "hi": {
        "payment_link": (
            "Aapka payment of {amount} pending hai. Yahan se pay karein:\n{payment_link}\n\n"
            "Koi madad chahiye toh reply karein."
        ),
        "invoice": (
            "Aapka invoice for {amount}:\n{invoice_link}\n\n"
            "Koi sawal ho toh batayein."
        ),
        "already_paid": (
            "Aapne payment kar diya hai — hum check kar rahe hain.\n\n"
            "Agar confirm ho jayega toh aapko message aayega. "
            "Koi issue hai toh hum aapko contact karenge."
        ),
        "promise_to_pay": (
            "Shukriya! Humne aapka promise note kar liya hai.\n\n"
            "Hum schedule ke hisaab se follow up karenge. "
            "Abhi pay karna chahein toh yahan se karein:\n{payment_link}\n\n"
            "Payment plan chahiye toh batayein."
        ),
        "payment_plan": (
            "Hum samajh rahe hain aap payment plan chahte hain.\n\n"
            "Hum aapke {amount} ko kai kiston mein split kar sakte hain. "
            "Humari team jald hi aapko plan options bhejegi.\n\n"
            "Tab tak aap puri amount yahan se pay kar sakte hain:\n{payment_link}"
        ),
        "question": (
            "Aapke sawal ka jawab:\n\n"
            "• Aapka pending payment hai {amount}\n"
            "• Aap yahan se pay kar sakte hain: {payment_link}\n"
            "• Zyada madad chahiye toh humare support team se baat karein\n\n"
            "Aur kuch chahiye toh batayein."
        ),
        "negative": (
            "Hum aapki baat samajh rahe hain. Iske liye maafi chahte hain.\n\n"
            "Humne aapka feedback note kar liya hai. "
            "Kuch discuss karna ho ya payment mein madad chahiye toh reply karein.\n\n"
            "Hum hamesha madad ke liye hain."
        ),
        "stop": (
            "Humne aapka stop request note kar liya hai.\n\n"
            "Ab aapko payment reminders nahi aayenge. "
            "Agar koi pending payment hai toh aap kabhi bhi pay kar sakte hain."
        ),
        "unclear": (
            "Hum aapka message samajh nahi paaye. Kripya batayein:\n\n"
            "• Aap payment karna chahte hain?\n"
            "• Aapko payment link chahiye?\n"
            "• Ya kuch aur madad chahiye?\n\n"
            "Aapka pending payment hai {amount}. Yahan se pay karein: {payment_link}"
        ),
        "payment_retry": (
            "Aap {amount} ka payment phir se kar sakte hain:\n{payment_link}\n\n"
            "Payment fir fail hota hai toh humein batayein — hum help karenge."
        ),
        # Recovery Specialist intents
        "pay_now": (
            "Yeh raha aapka direct payment link {amount} ke liye:\n{payment_link}\n\n"
            "Kabhi bhi click karke pay karein."
        ),
        "split_emi": (
            "Hum aapke {amount} ko kiston mein split kar sakte hain.\n\n"
            "Apna plan activate karne ke liye yahan click karein:\n{payment_link}"
        ),
        "pay_later": (
            "Koi baat nahi! Humne reminders pause kar diye hain.\n\n"
            "Aapka payment link {amount} ke liye active rahega:\n{payment_link}\n\n"
            "Kis din pay karna chahenge? Reply mein date bata dein."
        ),
        "greeting": (
            "Namaste! Aapki pending payment {amount} ke liye hai.\n\n"
            "Kya aap aaj poora bhugtan karna chahenge ya kishton mein baantein?"
        ),
        "fallback": (
            "Maaf kijiye, main theek se samajh nahi paya.\n\n"
            "Kya aap poora bhugtan karna chahenge, kishton mein, ya support se baat karein? "
            "Aapka pending payment {amount} hai: {payment_link}"
        ),
        "support": (
            "Main abhi hamari human support team ko connect kar raha hoon.\n\n"
            "Koi 2-3 minute mein issi chat mein aayega ya yahin reply karega."
        ),
    },
    "hi-en": {
        "payment_link": (
            "Aapka payment of {amount} pending hai. Yahan se pay karein:\n{payment_link}\n\n"
            "Koi madad chahiye toh reply karein."
        ),
        "invoice": (
            "Aapka invoice for {amount}:\n{invoice_link}\n\n"
            "Koi sawal ho toh batayein."
        ),
        "already_paid": (
            "Aapne payment kar diya hai — hum check kar rahe hain.\n\n"
            "Agar confirm ho jayega toh aapko message aayega. "
            "Koi issue hai toh hum aapko contact karenge."
        ),
        "promise_to_pay": (
            "Shukriya! Humne aapka promise note kar liya hai.\n\n"
            "Hum schedule ke hisaab se follow up karenge. "
            "Abhi pay karna chahein toh yahan se karein:\n{payment_link}\n\n"
            "Payment plan chahiye toh batayein."
        ),
        "payment_plan": (
            "Hum samajh rahe hain aap payment plan chahte hain.\n\n"
            "Hum aapke {amount} ko kai kiston mein split kar sakte hain. "
            "Humari team jald hi aapko plan options bhejegi.\n\n"
            "Tab tak aap puri amount yahan se pay kar sakte hain:\n{payment_link}"
        ),
        "question": (
            "Aapke sawal ka jawab:\n\n"
            "• Aapka pending payment hai {amount}\n"
            "• Aap yahan se pay kar sakte hain: {payment_link}\n"
            "• Zyada madad chahiye toh humare support team se baat karein\n\n"
            "Aur kuch chahiye toh batayein."
        ),
        "negative": (
            "Hum aapki baat samajh rahe hain. Iske liye maafi chahte hain.\n\n"
            "Humne aapka feedback note kar liya hai. "
            "Kuch discuss karna ho ya payment mein madad chahiye toh reply karein.\n\n"
            "Hum hamesha madad ke liye hain."
        ),
        "stop": (
            "Humne aapka stop request note kar liya hai.\n\n"
            "Ab aapko payment reminders nahi aayenge. "
            "Agar koi pending payment hai toh aap kabhi bhi pay kar sakte hain."
        ),
        "unclear": (
            "Hum aapka message samajh nahi paaye. Kripya batayein:\n\n"
            "• Aap payment karna chahte hain?\n"
            "• Aapko payment link chahiye?\n"
            "• Ya kuch aur madad chahiye?\n\n"
            "Aapka pending payment hai {amount}. Yahan se pay karein: {payment_link}"
        ),
        "payment_retry": (
            "Aap {amount} ka payment phir se kar sakte hain:\n{payment_link}\n\n"
            "Payment fir fail hota hai toh humein batayein — hum help karenge."
        ),
        # Recovery Specialist intents
        "pay_now": (
            "Yeh raha aapka direct payment link {amount} ke liye:\n{payment_link}\n\n"
            "Kabhi bhi click karke pay karein."
        ),
        "split_emi": (
            "Hum aapke {amount} ko kiston mein split kar sakte hain.\n\n"
            "Apna plan activate karne ke liye yahan click karein:\n{payment_link}"
        ),
        "pay_later": (
            "Koi baat nahi! Humne reminders pause kar diye hain.\n\n"
            "Aapka payment link {amount} ke liye active rahega:\n{payment_link}\n\n"
            "Kis din pay karna chahenge? Reply mein date bata dein."
        ),
        "greeting": (
            "Namaste! Aapki pending payment {amount} ke liye hai.\n\n"
            "Kya aap aaj poora bhugtan karna chahenge ya kishton mein baantein?"
        ),
        "fallback": (
            "Maaf kijiye, main theek se samajh nahi paya.\n\n"
            "Kya aap poora bhugtan karna chahenge, kishton mein, ya support se baat karein? "
            "Aapka pending payment {amount} hai: {payment_link}"
        ),
        "support": (
            "Main abhi hamari human support team ko connect kar raha hoon.\n\n"
            "Koi 2-3 minute mein issi chat mein aayega ya yahin reply karega."
        ),
    },
    "or": {
        "payment_link": (
            "Apanara {amount} payment karibaku ebe link:\n{payment_link}\n\n"
            "Kichhi sahajya darkar hele reply karantu."
        ),
        "invoice": (
            "Apanara {amount} pain invoice:\n{invoice_link}\n\n"
            "Kichhi prashna thile kahantu."
        ),
        "already_paid": (
            "Apana payment karideichanti — aame check karuchu.\n\n"
            "Confirm hele apananku message asiba. "
            "Kichhi problem thile apananku contact karibu."
        ),
        "promise_to_pay": (
            "Dhanyabad! Apanara promise aame note karideichu.\n\n"
            "Aame schedule anusara follow up karibu. "
            "Ebe pay karibaku chahile eithire karantu:\n{payment_link}\n\n"
            "Payment plan darkar hele kahantu."
        ),
        "payment_plan": (
            "Apana payment plan karibaku chahunchanti aame bujhuchu.\n\n"
            "Apanara {amount} ku kichhi kista re split karipariba. "
            "Amar team shighra apananku plan options padera deba.\n\n"
            "Sethipain apana pura amount eithire pay karipariba:\n{payment_link}"
        ),
        "question": (
            "Apanara prashnara uttara:\n\n"
            "• Apanara pending payment {amount}\n"
            "• Apana eithire pay karipariba: {payment_link}\n"
            "• Beshi sahajya darkar hele amar support team sathire kathaa karantu\n\n"
            "Aau kichhi darkar hele kahantu."
        ),
        "negative": (
            "Apanara katha aame bujhuchu. E pain khedita aachu.\n\n"
            "Apanara feedback aame note karideichu. "
            "Kichhi discuss kariba ki payment sahajya darkar hele reply karantu.\n\n"
            "Aame sad bada sahajya pain aachu."
        ),
        "stop": (
            "Apanara stop request aame note karideichu.\n\n"
            "Ebe apananku payment reminders asiba nahin. "
            "Kichhi pending payment thile apana kebe bi pay karipariba."
        ),
        "unclear": (
            "Apanara message aame bujhiparilu nahin. Kripya kahantu:\n\n"
            "• Apana pay karibaku chahunchanti?\n"
            "• Apananku payment link darkar?\n"
            "• Kimba aau kichhi sahajya darkar?\n\n"
            "Apanara pending payment {amount}. Eithire pay karantu: {payment_link}"
        ),
        "payment_retry": (
            "Apana {amount} payment puni karipariba:\n{payment_link}\n\n"
            "Payment puni fail hele apana amaku kahantu — aame sahajya karibu."
        ),
        # Recovery Specialist intents
        "pay_now": (
            "Apana direct payment link {amount} pain:\n{payment_link}\n\n"
            "Kebe bi click karipariba."
        ),
        "split_emi": (
            "Apana {amount} ku kichhi kista re split karipariba.\n\n"
            "Plan activate karibaku eithire click karantu:\n{payment_link}"
        ),
        "pay_later": (
            "Kichhi nahi! Aame reminders pause karideichu.\n\n"
            "Apana payment link {amount} pain active rahiba:\n{payment_link}\n\n"
            "Kete dinare pay karibaku chahunchanti? Reply re date kahantu."
        ),
        "greeting": (
            "Namaste! Apana pending payment {amount} pain aachi.\n\n"
            "Apana aji pura pay karibaku chahunchanti ki kista re?"
        ),
        "fallback": (
            "Maaf karantu, aame bujhiparilu nahin.\n\n"
            "Apana pura pay karibaku chahunchanti, kista re, ki support sathire kathaa karantu? "
            "Apana pending payment {amount}: {payment_link}"
        ),
        "support": (
            "Aame apana mananku human support team sathire connect karuchu.\n\n"
            "Kichhi minute bhitare ehi chat re asiba."
        ),
    },
}


# --- Language Detection ---

def detect_language(message: str) -> str:
    """Detect the language of a customer message.

    Uses script detection and keyword matching.
    Returns language code: 'en', 'hi', 'hi-en', 'or'.

    Detection priority:
    1. Odia script (Oriya Unicode block)
    2. Devanagari script (Hindi)
    3. Roman script with Hindi keywords (Hinglish)
    4. Default: English
    """
    # Check for Odia script (Unicode range: 0B00-0B7F)
    if re.search(r"[\u0B00-\u0B7F]", message):
        return "or"

    # Check for Devanagari script (Hindi) (Unicode range: 0900-097F)
    if re.search(r"[\u0900-\u097F]", message):
        return "hi"

    # Check for Hinglish (Roman script with Hindi keywords)
    hinglish_keywords = [
        r"\bhai\b", r"\bhaii\b", r"\bkaro\b", r"\bkarunga\b", r"\bkarigya\b",
        r"\bdunga\b", r"\bdey\b", r"\bsey\b", r"\bmein\b", r"\bko\b",
        r"\bkal\b", r"\bab\b", r"\bbahut\b", r"\bachha\b", r"\btheek\b",
        r"\bpakka\b", r"\bjarur\b", r"\bkyun\b", r"\bkyaa\b", r"\bkaise\b",
        r"\bbhai\b", r"\byaar\b", r"\bchahiye\b", r"\bchahiye\b",
        r"\bhoraha\b", r"\bnahi\b", r"\bhaan\b", r"\bji\b", r"\bdiya\b", r"\bkar\b", r"\bchuka\b", r"\bhoga\b", r"\bdey\b", r"\bsey\b",
        r"\bkaro*unga\b", r"\bpay\b.*\bkaro*unga\b", r"\bphir\b",
        r"\bdobara\b", r"\blink\b.*\bbhejo\b", r"\blink\b.*\bdo\b",
    ]
    msg_lower = message.lower()
    hinglish_matches = sum(1 for p in hinglish_keywords if re.search(p, msg_lower))
    if hinglish_matches >= 1:
        return "hi-en"

    # Default: English
    return "en"


def get_response_template(intent_key: str, language: str) -> str:
    """Get the response template for an intent in a specific language.

    Falls back to English if the language is not supported.
    """
    lang_templates = RESPONSE_TEMPLATES.get(language, RESPONSE_TEMPLATES["en"])
    return lang_templates.get(intent_key, RESPONSE_TEMPLATES["en"].get(intent_key, ""))


def get_patterns_for_language(language: str) -> LanguagePatterns:
    """Get intent classification patterns for a language.

    Falls back to English patterns if the language is not supported.
    """
    return PATTERNS.get(language, PATTERNS["en"])


def is_supported_language(lang: str) -> bool:
    """Check if a language is supported."""
    return lang in SUPPORTED_LANGUAGES
