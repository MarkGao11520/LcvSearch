import redis
from django.shortcuts import render
from django.views.generic.base import View
from search.models import JobboleType
from django.http import HttpResponse
import json
from elasticsearch import Elasticsearch
from datetime import datetime

# es客户端
client = Elasticsearch(hosts=["127.0.0.1"])
# redis客户端
redis_cli = redis.StrictRedis(host="localhost")


# 首页
class IndexView(View):

    # 处理get请求
    @staticmethod
    def get(request):
        # 获取redis中排名前5的搜索集合
        topn_search = redis_cli.zrevrangebyscore("search_keywrds_set",
                                                 "+inf",
                                                 "-inf",
                                                 start=0,
                                                 num=5)

        return render(request, "index.html", {"topn_search": topn_search})


# 首页搜索建议
class SearchSuggest(View):
    
    # 处理get请求
    @staticmethod
    def get(request):
        # 获取参数，默认为空
        key_words = request.GET.get('s', '')
        # 获取选项卡
        s_type = request.GET.get("s_type", "jobbole")
        print(s_type)
        # es关键字搜索 返回结果集
        re_data_list = []
        # 如果查询关键字参数存在才进行搜索
        if key_words:
            # 获取查询对象
            s = JobboleType.search()
            # 构建查询条件 —> 定义查询名:my-suggest,查询关键字:key_words
            # 查询类型为搜索建议，模糊性为2，最多查询10条
            s = s.suggest('my-suggest', key_words, completion={
                "field": "suggest", "fuzzy": {
                    "fuzziness": 2
                },
                "size": 10
            })
            # 执行查询获取返回结果
            suggestions = s.execute_suggest()

            # 遍历返回结果，封装到re_data_list里
            for match in getattr(suggestions, "my-suggest")[0].options:
                source = match._source
                re_data_list.append(source["title"])
        # 返回,媒体类型为json,返回结果为re_data_list
        return HttpResponse(json.dumps(re_data_list), content_type="application/json")


# 搜索结果页
class SearchView(View):
    # 处理get请求
    @staticmethod
    def get(request):
        # 获取搜索参数
        key_words = request.GET.get("q", "")
        # 获取选项课（文章，问答，职位）
        s_type = request.GET.get("s_type", "jobbole")
        print(s_type)
        # 获取页数
        page = request.GET.get("p", "1")
        # 从redis中获取伯乐在线记录总数
        jobbole_count = redis_cli.get("jobbole_count")
        # 从redis中获取知乎记录总数
        zhihu_count = redis_cli.get("zhihu_count")
        # 从redis中获取拉钩记录总数
        lagou_count = redis_cli.get("lagou_count")

        # redis中当前查询关键字搜索数加1
        redis_cli.zincrby("search_keywords_set", key_words)

        # 获取redis中排名前5的搜索集合
        topn_search = redis_cli.zrevrangebyscore("search_keywords_set",
                                                 "+inf",
                                                 "-inf",
                                                 start=0,
                                                 num=5)
        try:
            # 将获取的页面参数转型为整数
            page = int(page)
        except:
            # 若转型失败，默认为1
            page = 1

        # 开始查询时间
        start_time = datetime.now()
        # 开始es查询
        response = client.search(
            # 查询索引名称
            index="jobbole",
            # 查询体
            body={
                # 查询
                "query": {
                    # 多字段匹配
                    "multi_match": {
                        # 查询参数
                        "query": key_words,
                        # 匹配字段
                        "fields": ["tags", "title", "content"]
                    }
                },
                # 查询开始下标
                "from": (page - 1) * 10,
                # 查询总数
                "size": 10,
                # 高亮及包装字体
                "highlight": {
                    # 关键字前的包装html
                    "pre_tags": ['<span class="keyWord">'],
                    # 关键字后的包装html
                    "post_tags": ["</span>"],
                    # 需要包装的字段
                    "fields": {
                        "title": {},
                        "content": {}
                    }
                }
            }
        )

        # 结束查询时间
        end_time = datetime.now()
        # 计算总查询时间
        last_seconds = (end_time - start_time).total_seconds()
        # 获取查询返回结果总数
        total_nums = response["hits"]["total"]
        # 计算页数
        if (page % 10) > 0:
            page_nums = int(total_nums / 10) + 1
        else:
            page_nums = int(total_nums / 10)
        # 查询结果包装
        hit_list = []
        # 遍历es查询结果
        for hit in response["hits"]["hits"]:
            hit_dict = {}
            # 标题-判断本条查询结果是否是带查询参数，如果带，则使用高亮字体，否则使用普通文本
            if "highlight" in hit and "title" in hit["highlight"]:
                hit_dict["title"] = "".join(hit["highlight"]["title"])
            else:
                hit_dict["title"] = "".join(hit["_source"]["title"])

            # 内容-判断本条查询结果是否是带查询参数，如果带，则使用高亮字体，否则使用普通文本
            if "highlight" in hit and "content" in hit["highlight"]:
                # :500是截取500个字符 最后拼接</span> 是为了防止前面截取的字符串导致span没有争取结束而格式混乱
                hit_dict["content"] = "".join(hit["highlight"]["content"])[:500]+"</span>"
            else:
                hit_dict["content"] = "".join(hit["_source"]["content"])[:500]+"</span>"

            # 文章创建时间
            hit_dict["create_date"] = hit["_source"]["create_date"]
            # 文章url
            hit_dict["url"] = hit["_source"]["url"]
            # 匹配精确度分值
            hit_dict["score"] = hit["_score"]

            # 将本条结果追加到结果集列表里
            hit_list.append(hit_dict)

        # 返回界面
        return render(request, "result.html", {"page": page,
                                               "total_nums": total_nums,
                                               "all_this": hit_list,
                                               "key_words": key_words,
                                               "page_nums": page_nums,
                                               "last_seconds": last_seconds,
                                               "jobbole_count": jobbole_count,
                                               "lagou_count": lagou_count,
                                               "zhihu_count": zhihu_count,
                                               "topn_search": topn_search})
