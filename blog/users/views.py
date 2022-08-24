from django.shortcuts import render

# Create your views here.
from django.views import View
from django.http.response import HttpResponseBadRequest
import re
from users.models import User
from django.db import DatabaseError
from django.shortcuts import redirect
from django.urls import reverse


class RegisterView(View):

    def get(self, request):
        return render(request, 'register.html')

    def post(self, request):
        """
        1. 接收数据
        2. 验证数据
            2.1 参数是否齐全
            2.2 手机号的格式是否正确
            2.3 密码是否符合格式
            2.4 密码和确认密码要一致
            2.5 短信验证码是否和redis中一致
        3. 保存注册信息
        4. 返回响应跳转到指定页面
        """
        # 1. 接收数据
        mobile = request.POST.get('mobile')
        password = request.POST.get('password')
        password2 = request.POST.get('password2')
        smscode = request.POST.get('sms_code')
        # 2. 验证数据
        #     2.1 参数是否齐全
        if not all([mobile, password, password2, smscode]):
            return HttpResponseBadRequest('缺少必要的参数！')
        #     2.2 手机号的格式是否正确
        if False:
            return HttpResponseBadRequest('手机号不符合规则！')
        #     2.3 密码是否符合格式
        if False:
            return HttpResponseBadRequest('请输入符合规则的密码！')
        #     2.4 密码和确认密码要一致
        if password != password2:
            return HttpResponseBadRequest('两次密码不一致')
        #     2.5 短信验证码是否和redis中一致
        redis_conn = get_redis_connection('default')
        redis_sms_code = redis_conn.get('sms:%s' % mobile)
        if redis_sms_code is None:
            return HttpResponseBadRequest('短信验证码已过期!')
        if smscode != redis_sms_code.decode():
            return HttpResponseBadRequest('短信验证码不一致！')
        # 3. 保存注册信息
        # create_user 可以使用系统的方法对密码进行加密
        try:
            user = User.objects.create_user(username=mobile, mobile=mobile, password=password)
        except DatabaseError as e:
            logger.error(e)
            return HttpResponseBadRequest('注册失败！')
        # 状态保持
        from django.contrib.auth import login
        login(request, user)
        # 4. 返回响应跳转到指定页面, reverse是可以通过namespace来获取到视图对应的路由
        # 设置session
        response = redirect(reverse('home:index'))
        response.set_cookie('is_login', True)
        response.set_cookie('username', user.username, max_age=7 * 24 * 3600)
        return response


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
        CCP().send_template_sms(mobile, [sms_code, 5], 1)
        # 6.返回响应
        return JsonResponse({'code': RETCODE.OK, 'errmsg': '短信发送成功'})


class LoginView(View):
    def get(self, request):
        return render(request, 'login.html')

    def post(self, request):
        # 1.接收参数
        mobile = request.POST.get('mobile')
        password = request.POST.get('password')
        remember = request.POST.get('remember')
        #     1.1验证手机号
        pass
        #     2.1验证密码是否符合规则
        pass
        # 2.参数的验证，采用系统自带的认证方式进行验证
        from django.contrib.auth import authenticate
        user = authenticate(mobile=mobile, password=password)
        if user is None:
            return HttpResponseBadRequest('用户名或密码错误')
        # 3.用户认证登录
        from django.contrib.auth import login
        login(request, user)
        next_page = request.GET.get('next')
        if next_page:
            response = redirect(next_page)
        # 4.状态的保持
        # 5.根据用户选择的是否记住登录状态来进行判断
        # 6.为了首页显示，我们需要设置一些cookie信息
        else:
            response = redirect(reverse('home:index'))
        if remember != 'on':
            # 浏览器关闭之后
            request.session.set_expiry(0)
            response.set_cookie('is_login', True)
            response.set_cookie('username', user.username, max_age=14 * 24 * 3600)
        else:
            request.session.set_expiry(None)  # 默认记住两周
            response.set_cookie('is_login', True, max_age=14 * 24 * 3600)
            response.set_cookie('username', user.username, max_age=14 * 24 * 3600)
        # 7.返回响应
        return response


from django.contrib.auth import logout


class LogoutView(View):

    def get(self, request):
        # 1.session数据清除
        logout(request)
        # 2.删除部分cookie数据
        response = redirect(reverse('home:index'))
        response.delete_cookie('is_login')
        # 3.跳转到首页
        return response


class ForgetPasswordView(View):
    def get(self, request):
        return render(request, 'forget_password.html')

    def post(self, request):
        # 1.接收数据
        mobile = request.POST.get('mobile')
        password = request.POST.get('password')
        password2 = request.POST.get("password2")
        smscode = request.POST.get('sms_code')
        #
        # 2.验证数据
        #     2.1判断参数是否齐全
        if not all([mobile, password, password2, smscode]):
            return HttpResponseBadRequest('参数不全')
        #     2.2手机号和密码是否符合规则
        pass
        #     2.3判断确认密码和密码是否一致
        if password2 != password:
            return HttpResponseBadRequest('密码不一致')
        #     2.4判断短信验证码是否正确
        redis_conn = get_redis_connection('default')
        redis_sms_code = redis_conn.get("sms:%s" % mobile)
        if redis_sms_code is None:
            return HttpResponseBadRequest('短信验证码已过期')
        if redis_sms_code.decode() != smscode:
            return HttpResponseBadRequest('短信验证码错误')
        # 3.根据手机号进行用户信息查询
        try:
            user = User.objects.get(mobile=mobile)
        except User.DoesNotExist:
            # 5.如果手机号没有查询出用户信息，则进行新用户创建
            try:
                User.objects.create_user(username=mobile, mobile=mobile, password=password)
            except Exception:
                return HttpResponseBadRequest('修改失败，请稍后再试')
        else:
            # 4.如果手机号查询出用户信息，则进行用户信息的修改
            user.set_password(password)
            user.save()
            pass
        # 6.进行页面跳转，到登录页面
        response = redirect(reverse('users:login'))
        # 7.返回响应
        return response


# 如果用户未登录，会自动跳转
from django.contrib.auth.mixins import LoginRequiredMixin


class UserCenterView(LoginRequiredMixin, View):
    def get(self, request):
        # 获取登录用户的信息
        user = request.user
        # 组织获取用户的信息
        context = {
            'username': user.username,
            'mobile': user.mobile,
            'avatar': user.avatar.url if user.avatar else None,
            'user_desc': user.user_desc
        }
        return render(request, "center.html", context=context)

    def post(self, request):
        # 1.接收参数
        user = request.user
        username = request.POST.get('username', user.username)
        user_desc = request.POST.get('desc', user.user_desc)
        avatar = request.FILES.get('avatar')
        # 2.将参数保存起来
        try:
            user.username = username
            user.user_desc = user_desc
            if avatar:
                user.avatar = avatar
            user.save()
        except Exception as e:
            logger.error(e);
            return HttpResponseBadRequest('修改失败，请稍后再试')
        # 3.更新cookie中的username信息
        # 4.刷新当前页面(重定向操作)
        response = redirect(reverse('users:center'))
        response.set_cookie('username', user.username, max_age=14*3600*24)
        # 5.返回响应
        return response

