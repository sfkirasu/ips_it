import json
import time
import pathlib
import datetime
import requests
import mimetypes

from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as ec

import webscraper

class IPSScraper(webscraper.BaseScraper):
    def fetch_categories(self) -> dict:
        self.driver.get(self.website_config['url'])
        WebDriverWait(self.driver, 100).until(
            ec.presence_of_all_elements_located((By.TAG_NAME, 'a'))
        )
        categories = {}
        # div_element = self.driver.find_element(By.CLASS_NAME, 'container main-navigation')
        div_element = self.driver.find_element(By.TAG_NAME, 'nav')
        div_element = div_element.find_element(By.CLASS_NAME, 'sf-menu')
        for a in div_element.find_elements(By.TAG_NAME, 'a'):
            pre_class = str(a.get_attribute('innerText'))
            categories[pre_class] = str(a.get_attribute('href'))
        return categories


    def _run(self):
        with webscraper.running('Loading all articles of the category', timer=True) as spinner:
            urls = self.get_all_urls()
            spinner.write(f'Found {len(urls)} articles')
        with webscraper.running('Scraping and saving articles', spinner=False):
            if self.debug:
                urls = urls[:3]
            for url in webscraper.tqdm(urls[:10]):
                self.download_article(url)

    def _download_article(self, url: str):
        self.driver.get(url)
        # 等待加载所有图像和元素
        try:
            WebDriverWait(self.driver, 50).until(ec.presence_of_all_elements_located((By.TAG_NAME, 'img')))
            WebDriverWait(self.driver, 50).until(ec.presence_of_all_elements_located((By.TAG_NAME, 'div')))
        except Exception as e:
            print(webscraper.text(f'Cannot load all images and elements: {e}', style=webscraper.WARNING))
        # 向下滚动页面以确保加载所有延迟加载的图像
        try:
            self.scroll_down()
        except Exception as e:
            print(webscraper.text(f'Cannot scroll down the page: {e}', style=webscraper.WARNING))
        # 获取页面
        response = self.driver.execute_cdp_cmd('Page.captureSnapshot', {})
        # 获取文章信息
        info, save_dir, article = self.extract_article()
        # 如果获取到文章
        if info is not None:
            self.extract_images(info, article)
            # 写入文件
            with open(save_dir / 'article.mhtml', 'w', newline='') as f:
                f.write(response['data'])
        else:
            print(webscraper.text(f'Cannot extract article: {url}', style=webscraper.WARNING))

    def extract_article(self) -> tuple[dict | None, pathlib.Path | None, webscraper.database.Article | None]:
        try:
            # 获取文章信息
            info = {
                'url': self.driver.current_url,
                'website': self.website_config['code'],
                'language': self.website_config['language'],
                'category': self.category,
            }
            title = self.driver.find_element(By.XPATH, '//h1[contains(@class, "entry-title")]')
            info['title'] = webscraper.sanitize_str(str(title.text))
            post_time = self.driver.find_element(By.XPATH, '//time[contains(@class,"entry-date published updated")]')
            # 获取时间
            temp_time = post_time.get_attribute('datetime')
            if temp_time is None:
                info['post_time'] = post_time.text.split(', ')
            else:
                info['post_time'] = temp_time
            content = ''
            div = self.driver.find_element(By.XPATH, '//div[contains(@class,"clearfix entry-content")]')
            for p in div.find_elements(By.TAG_NAME, 'p'):
                content += (p.text + '\n')
            info['content'] = webscraper.sanitize_str(content)
            info['extract_time'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            # 获取文章名后创建目录
            save_dir = self.output_path / webscraper.sanitize_filename(info['title'])
            save_dir.mkdir(parents=True, exist_ok=True)
            # 写入文件保存
            with open(save_dir / 'article.json', 'w', encoding='utf-8') as json_file:
                json.dump(info, json_file, ensure_ascii=False, indent=2)
            article = webscraper.database.commit_article(self.db_engine, info)
            # 返回文章信息的键值对，以及
            return info, save_dir, article
        except Exception as e:
            print(webscraper.text(f'Cannot extract article: {e}', style=webscraper.WARNING))
            return None, None, None

    def extract_images(self, info: dict, article: webscraper.database.Article):
        # 只在文章主体部分找图片，除去广告和其他链接
        # 获取到文章主体部分的大标签
        div = self.driver.find_element(By.XPATH, '//div[contains(@class,"entry-thumbnail") or contains(@class,"wp-caption alignright")]')
        img_elements = div.find_elements(By.TAG_NAME, 'img')
        # 保存图片序号
        index = 0
        # 遍历图片元素并下载图片
        for img in img_elements:
            img_url = img.get_attribute('src')
            img_alt = img.get_attribute('alt')

            if "https" not in img_url:
                img_url = "https://ipsnews.net" + img_url

            if "cdn" in img_url:
                continue
            # 跳过没有src或alt属性的图片元素
            if not img_url:
                continue
            if not img_alt:
                img_alt = ''
            # 创建保存图片的目录
            save_dir = self.output_path / webscraper.sanitize_filename(info['title']) / 'images'
            save_dir.mkdir(parents=True, exist_ok=True)
            # 使用 requests 库下载图片，来保证图片下载完整
            response = requests.get(img_url)
            content_type = response.headers['content-type']
            extension = mimetypes.guess_extension(content_type)
            if response.status_code == 200:
                # 保存图片文件
                path = save_dir / f'image{index}{extension}'
                with open(path, 'wb') as f:
                    f.write(response.content)
                # 创建JSON文件保存图片相关信息
                json_data = {
                    'website': self.website_config['code'],
                    'language': self.website_config['language'],
                    'category': self.category,
                    'title': info['title'],
                    'post_time': info['post_time'],
                    'article_url': info['url'],
                    'caption': img_alt,
                    'url': img_url,
                    'extract_time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                # 将图文对信息保存
                path = save_dir / f'image{index}.json'
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(json_data, f, ensure_ascii=False, indent=2)
                webscraper.database.commit_image(self.db_engine, article, img_url, img_alt, json_data['extract_time'])
                index += 1
            else:
                print(webscraper.text(
                    f'Cannot download image: {img_url} status code: {response.status_code}',
                    style=webscraper.WARNING
                ))

    def get_all_urls(self) -> list[str]:
        urls = []
        self._base_url = self.base_url
        self.driver.get(self._base_url)
        WebDriverWait(self.driver, 100).until(
            ec.presence_of_all_elements_located((By.TAG_NAME, 'a'))
        )
        while True:
            try:
                # 获取所有文章链接
                div_element = self.driver.find_element(By.CLASS_NAME, 'site-content')
                div_elements = div_element.find_elements(By.CLASS_NAME, 'entry-title')
                for div in div_elements:
                    a_elements = div.find_elements(By.TAG_NAME, 'a')
                    for a in a_elements:
                        href = a.get_attribute('href')
                        urls.append(href)

                if self.debug:
                    break
                # 加载更多
                self.load_more()

            except Exception as e:
                print(webscraper.text(f'Cannot load more: {e}', style=webscraper.WARNING))
                break
        # 去重的同时保留顺序
        return list(dict.fromkeys(urls))


#old articles
def load_more(self):

        try:
            paging = WebDriverWait(self.driver, 150).until(
                ec.presence_of_element_located((By.CLASS_NAME, 'nav-previous'))
            )
            load_more = paging.find_element(By.CLASS_NAME, 'nav-previous')
            self._base_url = load_more.get_attribute('href')
            self.driver.get(self._base_url)
            # 等待页面加载完成
            WebDriverWait(self.driver, 100).until(
                ec.presence_of_all_elements_located((By.TAG_NAME, 'a'))
            )
            time.sleep(2)
        except Exception as e:
            raise e



