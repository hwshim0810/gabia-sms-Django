from __future__ import with_statement

import hashlib
import re

from django.conf import settings
from django.utils import timezone

from . import formats
from .exceptions import SMSModuleException
from .parser import get_result_code
from .utils import Singleton, escape_xml_string, get_nonce


try:
    import xmlrpc.client as xmlrpc_lib
except ImportError:
    import xmlrpclib as xmlrpc_lib


PHONE_NUMBER_REGEX = '01[0|1|6|7|8|9]{1}[0-9]{7,8}'

MISSING_SETTING = (
    'GABIA_SMS_SETTINGS {setting} is required'
)
REQUIRED_SETTINGS = ('API_ID', 'API_KEY', 'SENDER')
KNOWN_SMS_TYPES = ('sms', 'lms', 'multi_sms', 'multi_lms')
SINGLE_SMS_TYPES = ('sms', 'lms')
MULTI_SMS_TYPES = ('multi_sms', 'multi_lms')
SUCCESS_CODE = '0000'


class GabiaSMS:

    __API_URL = 'http://sms.gabia.com/api'
    __MODULE_SETTINGS_NAME = 'GABIA_SMS_SETTINGS'

    def __init__(self):
        self.__settings = self.__get_module_settings()
        self.__validate_settings()

    def __get_module_settings(self):
        module_settings = getattr(settings, self.__MODULE_SETTINGS_NAME, {})

        for setting_key in REQUIRED_SETTINGS:
            module_settings.setdefault(setting_key, None)

        return module_settings

    def __validate_settings(self):
        for key, value in self.__settings.items():
            if not value:
                raise SMSModuleException(MISSING_SETTING.format(setting=key))

    def __validate_required_params(self, message, receiver):
        if not (message and receiver):
            raise SMSModuleException('Please check required parameters!')
        elif not isinstance(message, str) or not isinstance(receiver, str):
            raise SMSModuleException('Please check parameters type!')
        elif not re.compile(PHONE_NUMBER_REGEX).search(receiver):
            raise SMSModuleException('Please check phone number!')

    def __validate_required_multi_params(self, message, receivers):
        if not (message and receivers):
            raise SMSModuleException('Please check required parameters!')
        elif not isinstance(receivers, list) or not isinstance(receivers, set):
            raise SMSModuleException('Please check parameters type!')

        for phone_number in receivers:
            if not re.compile(PHONE_NUMBER_REGEX).search(phone_number):
                raise SMSModuleException('Please check phone number!')

    def __get_md5_access_token(self):
        nonce = get_nonce()
        return nonce + hashlib.md5(
            (nonce + self.__settings['API_KEY']).encode()
        ).hexdigest()

    def post_sent_sms(self, *args, **kwargs):
        """
        Post sent sms task\n
        Do what you need to override
        """
        pass

    def before_send_sms(self, *args, **kwargs):
        """
        Before send sms task\n
        Do what you need to override
        """
        pass

    def __get_sms_param(self, message, receiver, title, scheduled_time, sms_type):

        if sms_type in SINGLE_SMS_TYPES:
            self.__validate_required_params(message, receiver)
        else:
            receivers = set(receiver)
            self.__validate_required_multi_params(message, receivers)

            receiver = ','.join(receivers)
            sms_type = sms_type[-3:]

        return {
            'sender': self.__settings['SENDER'],
            'sms_type': sms_type,
            'message': escape_xml_string(message),
            'receiver': receiver,
            'title': escape_xml_string(title),
            'scheduled_time': scheduled_time,
            'key': int(timezone.now().timestamp())
        }

    def send(self, message, receiver, title='SEND',
             sms_type='sms', scheduled_time='0', *args, **kwargs):
        """
        Use for send single SMS\n
        :param message: Message
        :param receiver: Receive Phone number:
               if 'multi_sms' or 'multi_lms' receiver type is list or set
        :param title: SMS TITLE: Used where the sms_type is 'lms' or 'multi_lms'
        :param sms_type: ['sms', 'lms', 'multi_sms', 'multi_lms'] : default value is 'sms'
        :param scheduled_time: default 0: send immediately or '%Y-%M-%D %h:%m:%s'
        :return Key of sent SMS
        """
        if sms_type not in KNOWN_SMS_TYPES:
            raise SMSModuleException('Please check sms type!')

        return self.__send_sms(
            self.__get_sms_param(message, receiver, title, scheduled_time, sms_type),
            *args,
            **kwargs
        )

    def get_send_result(self, key):
        """
        :param key: The key to lookup
        :return: Result code received by key
        """
        with xmlrpc_lib.ServerProxy(self.__API_URL) as proxy:
            try:
                response = proxy.gabiasms(
                    formats.REQUEST_SMS_RESULT_FORMAT.format(
                        api_id=self.__settings['API_ID'],
                        access_token=self.__get_md5_access_token(),
                        key=key
                    )
                )
                return get_result_code(response)

            except xmlrpc_lib.Error as e:
                import logging
                logging.getLogger(__name__).error(e)
                raise SMSModuleException('Bad request. Please check api docs')

    def __send_sms(self, param, *args, **kwargs):

        with xmlrpc_lib.ServerProxy(self.__API_URL) as proxy:
            try:
                self.before_send_sms(param, *args, **kwargs)

                sms_type = param['sms_type']

                if sms_type in SINGLE_SMS_TYPES:
                    request_format = formats.REQUEST_SMS_XML_FORMAT
                else:
                    request_format = formats.REQUEST_MULTI_SMS_XML_FORMAT

                response = proxy.gabiasms(
                    request_format.format(
                        api_id=self.__settings['API_ID'],
                        access_token=self.__get_md5_access_token(),
                        sms_type=sms_type,
                        key=param['key'],
                        title=param['title'],
                        message=param['message'],
                        sender=param['sender'],
                        receiver=param['receiver'],
                        scheduled_time=param['scheduled_time']
                    )
                )
                result_code = get_result_code(response)

                if result_code != SUCCESS_CODE:
                    import logging
                    logging.getLogger(__name__).debug(result_code)

                self.post_sent_sms(param, *args, **kwargs)

                return param['key']

            except xmlrpc_lib.Error as e:
                import logging
                logging.getLogger(__name__).error(e)
                raise SMSModuleException('Bad request. Please check api docs')


class SingletonGabiaSMS(GabiaSMS, Singleton):
    pass
