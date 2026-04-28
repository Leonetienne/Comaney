"""Category and tag CRUD, including rename via inline editor."""
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC

from conftest import _url, click, wait_text


class TestCategoriesTags:

    def test_05_create_category(self, driver, w, ctx):
        driver.get(_url("/budget/categories-tags/"))
        inp = w.until(EC.element_to_be_clickable((By.ID, "category-input")))
        inp.send_keys("Test Category" + Keys.RETURN)
        w.until(lambda d: "Test Category" in d.find_element(By.ID, "category-list").text)

    def test_06_rename_category(self, driver, w, ctx):
        w.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#category-list .ct-name")))
        ctx["category_uid"] = driver.execute_script(
            "return document.querySelector('#category-list .ct-name').dataset.uid;")
        driver.execute_script(
            "var el=document.querySelector('#category-list .ct-name');"
            "el.scrollIntoView({block:'center'}); el.click();")
        w.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#category-list .ct-name-input")))
        driver.execute_script(
            "var inp=document.querySelector('#category-list .ct-name-input');"
            "inp.value='Renamed Category';"
            "inp.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));")
        time.sleep(0.5)
        driver.get(_url("/budget/categories-tags/"))
        wait_text(driver, w, "Renamed Category")

    def test_07_create_tag(self, driver, w, ctx):
        inp = w.until(EC.element_to_be_clickable((By.ID, "tag-input")))
        inp.send_keys("Test Tag" + Keys.RETURN)
        w.until(lambda d: "Test Tag" in d.find_element(By.ID, "tag-list").text)

    def test_08_rename_tag(self, driver, w, ctx):
        w.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#tag-list .ct-name")))
        ctx["tag_uid"] = driver.execute_script(
            "return document.querySelector('#tag-list .ct-name').dataset.uid;")
        driver.execute_script(
            "var el=document.querySelector('#tag-list .ct-name');"
            "el.scrollIntoView({block:'center'}); el.click();")
        w.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#tag-list .ct-name-input")))
        driver.execute_script(
            "var inp=document.querySelector('#tag-list .ct-name-input');"
            "inp.value='Renamed Tag';"
            "inp.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));")
        time.sleep(0.5)
        driver.get(_url("/budget/categories-tags/"))
        wait_text(driver, w, "Renamed Tag")
