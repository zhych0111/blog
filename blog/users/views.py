from django.shortcuts import render

# Create your views here.
from django.views import View


class RegisterView(View):

    def get(self, request):
        return render(request, 'register.html')


from django.http.response import HttpResponseBadRequest
from django.http import HttpResponse
from libs.captcha.captcha import captcha
from django_redis import get_redis_connection
from django.http.response import JsonResponse
from utils.response_code import RETCODE
import logging
logger = logging.getLogger('django')
from random import randint
from libs.yuntongxun.sms import CCP


class ImageCodeView(View):
    def get(self, request):
        """
        1. 接收前端传过来的uuid
        2. 判断uuid是否获取到
        3. 通过调用拷贝过来的captcha来生成图片验证码(图片二进制和图片内容)
        4. 将图片内容保存在redis中,uuid作为一个key，图片内容作为一个value，同时我们还需要设置一个实效
        5. 返回图片二进制
        """
        # 1.接收前端传过来的uuid
        uuid = request.GET.get('uuid')
        # 2.判断uuid是否获取到
        if uuid is None:
            return HttpResponseBadRequest('没有传递uuid')
        # 3.通过调用拷贝过来的captcha来生成图片验证码(图片二进制和图片内容)
        text, image = captcha.generate_captcha()  # 返回一个二元组
        # 4.将图片内容保存在redis中, uuid作为一个key，图片内容作为一个value，同时我们还需要设置一个实效
        redis_conn = get_redis_connection('default')
        # key 设置为uuid
        # seconds 过期秒数 300秒过期时间
        # value text
        redis_conn.setex('img:%s' % uuid, 300, text)
        # 5.返回图片二进制
        return HttpResponse(image, content_type='image/jpeg')


class SmsCodeView(View):

    def get(self, request):
        """
        1.接收参数(查询字符串的形式传递过来)
        2.参数的验证
            2.1 验证参数是否齐全
            2.2 图片验证码的验证
                2.2.1 连接redis，获取redis中的图片验证码
                2.2.2 判断图片验证码是否存在或者超时
                2.2.3 如果图片验证码未过期，获取到之后就可以删除图片验证码
                2.2.4 比对图片验证码
        3.生成短信验证码
        4.保存短信验证码到redis中
        5.发送短信
        6.返回响应
        """
        # 1.接收参数(查询字符串的形式传递过来)
        mobile = request.GET.get('mobile')
        image_code = request.GET.get('image_code')
        uuid = request.GET.get('uuid')
        # 2.参数的验证
        #     2.1 验证参数是否齐全
        if not all([mobile, image_code, uuid]):
            return JsonResponse({'code': RETCODE.NECESSARYPARAMERR, 'errmsg': '缺少必要的参数'})
        #     2.2 图片验证码的验证
        #         2.2.1 连接redis，获取redis中的图片验证码
        redis_conn = get_redis_connection('default')
        redis_image_code = redis_conn.get('img:%s' % uuid)
        #         2.2.2 判断图片验证码是否存在或者超时
        if redis_image_code is None:
            return JsonResponse({'code': RETCODE.IMAGECODEERR, 'errmsg': '图片验证码已过期'})
        #         2.2.3 如果图片验证码未过期，获取到之后就可以删除图片验证码
        try:
            redis_conn.delete('img:%s' % uuid)
        except Exception as e:
            logger.error(e)
        #         2.2.4 比对图片验证码, 注意大小写，redis的数据是byte类型
        if redis_image_code.decode().lower() != image_code.lower():
            return JsonResponse({'code': RETCODE.IMAGECODEERR, 'errmsg': '图片验证码错误'})
        # 3.生成短信验证码,为了后期比对方便，记录到日志中。
        sms_code = "%06d" % randint(0, 999999)
        logger.info(sms_code)
        # 4.保存短信验证码到redis中
        redis_conn.setex('sms:%s' % mobile, 300, sms_code)
        # 5.发送短信
        CCP().send_template_sms(mobile, ['1234', 5], 1)
        # 6.返回响应
        return JsonResponse({'code': RETCODE.OK, 'errmsg': '短信发送成功'})
